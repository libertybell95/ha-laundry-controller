"""Laundry state machine.

This module is deliberately free of Home Assistant imports so it can be unit
tested in isolation. Every public method is synchronous, takes the current
time explicitly and returns a list of side effects for the caller to perform.
The controller runs these methods inside the event loop without awaiting in
between, so transitions are strictly serialized.

Sensor trust policy
-------------------
A running-sensor reading that directly follows another known reading
(``on -> off`` or ``off -> on``) is acted on immediately. A reading that follows
``unknown``/``unavailable`` (or Home Assistant start-up) is *untrusted*: it must
remain unchanged for the reconnect grace period before it is reconciled
against the appliance phase. This prevents phantom cycles, duplicate load
counts and false completions when a sensor drops out and reconnects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class Appliance(StrEnum):
    """Laundry appliance."""

    WASHER = "washer"
    DRYER = "dryer"


class Phase(StrEnum):
    """Appliance lifecycle phase."""

    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"


# Public (entity) state names for each appliance phase.
PHASE_STATES: dict[Appliance, dict[Phase, str]] = {
    Appliance.WASHER: {
        Phase.IDLE: "idle",
        Phase.RUNNING: "washing",
        Phase.DONE: "wash_done",
    },
    Appliance.DRYER: {
        Phase.IDLE: "idle",
        Phase.RUNNING: "drying",
        Phase.DONE: "dry_done",
    },
}

# Combined status: (washer phase, dryer phase) -> status sensor state.
STATUS_STATES: dict[tuple[Phase, Phase], str] = {
    (Phase.IDLE, Phase.IDLE): "idle",
    (Phase.RUNNING, Phase.IDLE): "washing",
    (Phase.IDLE, Phase.RUNNING): "drying",
    (Phase.RUNNING, Phase.RUNNING): "washing_and_drying",
    (Phase.DONE, Phase.IDLE): "wash_done",
    (Phase.IDLE, Phase.DONE): "dry_done",
    (Phase.DONE, Phase.DONE): "wash_and_dry_done",
    (Phase.DONE, Phase.RUNNING): "wash_done_drying",
    (Phase.RUNNING, Phase.DONE): "washing_dry_done",
}


class Notice(StrEnum):
    """Phone notification kinds produced by transitions."""

    WASHER_FINISHED = "washer_finished"
    DRYER_FINISHED = "dryer_finished"


@dataclass(frozen=True, slots=True)
class FireEvent:
    """Fire a bus event (name without domain prefix)."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SendNotice:
    """Send a "current state" phone notification."""

    kind: Notice


@dataclass(frozen=True, slots=True)
class ClearNotices:
    """Clear phone notifications by category."""

    state: bool = False
    reminder: bool = False


@dataclass(frozen=True, slots=True)
class Announce:
    """Make a smart-speaker announcement for the dryer finishing."""


type Effect = FireEvent | SendNotice | ClearNotices | Announce


@dataclass(slots=True)
class ApplianceRecord:
    """State of a single appliance."""

    phase: Phase = Phase.IDLE
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_duration: timedelta | None = None
    last_reminded_at: datetime | None = None
    # Runtime only (not persisted): last running-sensor reading.
    reading: bool | None = None
    trusted: bool = False
    reading_since: datetime | None = None

    @property
    def pending(self) -> bool:
        """Return True while an untrusted reading awaits confirmation."""
        return self.reading is not None and not self.trusted

    def as_dict(self) -> dict[str, Any]:
        """Serialize persistent fields."""
        return {
            "phase": self.phase.value,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "last_duration": (
                self.last_duration.total_seconds() if self.last_duration else None
            ),
            "last_reminded_at": _iso(self.last_reminded_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ApplianceRecord:
        """Deserialize, tolerating missing or malformed fields."""
        data = data or {}
        try:
            phase = Phase(data.get("phase", Phase.IDLE))
        except ValueError:
            phase = Phase.IDLE
        duration = data.get("last_duration")
        return cls(
            phase=phase,
            started_at=_parse(data.get("started_at")),
            finished_at=_parse(data.get("finished_at")),
            last_duration=(
                timedelta(seconds=duration)
                if isinstance(duration, (int, float))
                else None
            ),
            last_reminded_at=_parse(data.get("last_reminded_at")),
        )


class LaundryStateMachine:
    """Washer/dryer state machine."""

    def __init__(
        self,
        *,
        reconnect_grace: timedelta = timedelta(seconds=120),
        notify_washer_while_dryer_running: bool = False,
    ) -> None:
        """Initialize."""
        self.reconnect_grace = reconnect_grace
        self.notify_washer_while_dryer_running = notify_washer_while_dryer_running
        self.records: dict[Appliance, ApplianceRecord] = {
            Appliance.WASHER: ApplianceRecord(),
            Appliance.DRYER: ApplianceRecord(),
        }
        self.loads = 0
        self.last_completed: datetime | None = None
        # Appliance whose "finished" notification currently occupies the
        # state notification tag, so it is only cleared when it is stale.
        self.state_notice_owner: Appliance | None = None

    # ------------------------------------------------------------------ views

    @property
    def washer(self) -> ApplianceRecord:
        """Washer record."""
        return self.records[Appliance.WASHER]

    @property
    def dryer(self) -> ApplianceRecord:
        """Dryer record."""
        return self.records[Appliance.DRYER]

    def state_of(self, appliance: Appliance) -> str:
        """Public state name of an appliance."""
        return PHASE_STATES[appliance][self.records[appliance].phase]

    @property
    def status(self) -> str:
        """Combined status."""
        return STATUS_STATES[(self.washer.phase, self.dryer.phase)]

    def waiting(self) -> list[Appliance]:
        """Appliances holding finished laundry (excluding unconfirmed ones)."""
        return [
            appliance
            for appliance, record in self.records.items()
            if record.phase is Phase.DONE and not record.pending
        ]

    @property
    def needs_attention(self) -> bool:
        """Return True if any appliance holds finished laundry."""
        return any(r.phase is Phase.DONE for r in self.records.values())

    def next_confirm_at(self) -> datetime | None:
        """When the earliest untrusted reading becomes eligible for confirmation."""
        times = [
            record.reading_since + self.reconnect_grace
            for record in self.records.values()
            if record.pending and record.reading_since is not None
        ]
        return min(times, default=None)

    # ----------------------------------------------------------------- inputs

    def activity(
        self, appliance: Appliance, reading: bool | None, now: datetime
    ) -> list[Effect]:
        """Handle a running-sensor reading (``None`` = unknown/unavailable)."""
        record = self.records[appliance]
        if reading is None:
            record.reading = None
            record.trusted = False
            record.reading_since = None
            return []
        if record.reading is not None and record.trusted:
            if reading == record.reading:
                return []
            record.reading = reading
            record.reading_since = now
            return self._apply(appliance, reading, now)
        if record.reading == reading:
            # Repeated untrusted reading: keep the original timestamp.
            return []
        record.reading = reading
        record.trusted = False
        record.reading_since = now
        if self.reconnect_grace <= timedelta(0):
            return self.confirm(now)
        return []

    def confirm(self, now: datetime) -> list[Effect]:
        """Trust readings that stayed stable for the grace period."""
        effects: list[Effect] = []
        for appliance, record in self.records.items():
            if (
                record.pending
                and record.reading_since is not None
                and record.reading_since + self.reconnect_grace <= now
            ):
                record.trusted = True
                assert record.reading is not None
                effects += self._apply(appliance, record.reading, record.reading_since)
        return effects

    def door_opened(self, appliance: Appliance, now: datetime) -> list[Effect]:
        """Handle a door opening (closed -> open)."""
        record = self.records[appliance]
        if record.phase is not Phase.DONE:
            return []
        self._set_idle(appliance)
        effects: list[Effect] = []
        if appliance is Appliance.DRYER:
            self.last_completed = now
            effects.append(
                FireEvent(
                    "laundry_cleared",
                    {"source": "dryer_door", "appliances": [appliance.value]},
                )
            )
        return effects + self._clear_notices([appliance])

    def hang_dry(self, now: datetime) -> list[Effect]:
        """Acknowledge the washer load as being hung to dry."""
        effects: list[Effect] = []
        if self.washer.phase is Phase.DONE:
            self._set_idle(Appliance.WASHER)
            effects.append(
                FireEvent(
                    "laundry_cleared",
                    {"source": "hang_dry", "appliances": [Appliance.WASHER.value]},
                )
            )
            effects += self._clear_notices([Appliance.WASHER])
        elif self.state_notice_owner is Appliance.WASHER:
            effects += self._clear_notices([Appliance.WASHER])
        return effects

    def mark_done(self, now: datetime, source: str) -> list[Effect]:
        """Acknowledge all finished laundry. Running appliances are untouched."""
        cleared = [a for a, r in self.records.items() if r.phase is Phase.DONE]
        for appliance in cleared:
            self._set_idle(appliance)
        effects: list[Effect] = []
        if cleared:
            self.last_completed = now
            effects.append(
                FireEvent(
                    "laundry_cleared",
                    {"source": source, "appliances": [a.value for a in cleared]},
                )
            )
        self.state_notice_owner = None
        effects.append(ClearNotices(state=True, reminder=True))
        return effects

    def reset(self, now: datetime) -> list[Effect]:
        """Discard finished states and re-sync phases with trusted readings."""
        for record in self.records.values():
            running = record.reading is True and record.trusted
            if running and record.phase is not Phase.RUNNING:
                record.started_at = now
            record.phase = Phase.RUNNING if running else Phase.IDLE
            record.last_reminded_at = None
        self.state_notice_owner = None
        return [ClearNotices(state=True, reminder=True)]

    def set_loads(self, loads: int) -> None:
        """Set the load counter."""
        self.loads = max(0, int(loads))

    def set_last_completed(self, when: datetime | None) -> None:
        """Set the last completed timestamp."""
        self.last_completed = when

    # -------------------------------------------------------------- internals

    def _apply(self, appliance: Appliance, on: bool, at: datetime) -> list[Effect]:
        record = self.records[appliance]
        if on and record.phase is not Phase.RUNNING:
            return self._start(appliance, at)
        if not on and record.phase is Phase.RUNNING:
            return self._finish(appliance, at)
        return []

    def _start(self, appliance: Appliance, at: datetime) -> list[Effect]:
        record = self.records[appliance]
        # A finished appliance starting again has evidently been emptied.
        cleared = [appliance] if record.phase is Phase.DONE else []
        record.phase = Phase.RUNNING
        record.started_at = at
        record.last_reminded_at = None
        if appliance is Appliance.WASHER:
            self.loads += 1
        elif self.washer.phase is Phase.DONE:
            # Clothes moved from the washer to the dryer.
            self._set_idle(Appliance.WASHER)
            cleared.append(Appliance.WASHER)
        data = {"loads": self.loads} if appliance is Appliance.WASHER else {}
        effects: list[Effect] = [FireEvent(f"{appliance.value}_started", data)]
        return effects + self._clear_notices(cleared)

    def _finish(self, appliance: Appliance, at: datetime) -> list[Effect]:
        record = self.records[appliance]
        record.phase = Phase.DONE
        record.finished_at = at
        record.last_reminded_at = None
        record.last_duration = (
            at - record.started_at
            if record.started_at and record.started_at <= at
            else None
        )
        data: dict[str, Any] = {
            "duration": (
                record.last_duration.total_seconds() if record.last_duration else None
            )
        }
        if appliance is Appliance.WASHER:
            dryer_running = self.dryer.phase is Phase.RUNNING
            effects: list[Effect] = [
                FireEvent("washer_finished", {**data, "dryer_running": dryer_running})
            ]
            if not dryer_running or self.notify_washer_while_dryer_running:
                self.state_notice_owner = Appliance.WASHER
                effects.append(SendNotice(Notice.WASHER_FINISHED))
            return effects
        self.state_notice_owner = Appliance.DRYER
        return [
            FireEvent("dryer_finished", data),
            SendNotice(Notice.DRYER_FINISHED),
            Announce(),
        ]

    def _set_idle(self, appliance: Appliance) -> None:
        record = self.records[appliance]
        record.phase = Phase.IDLE
        record.last_reminded_at = None

    def _clear_notices(self, cleared: list[Appliance]) -> list[Effect]:
        if not cleared:
            return []
        clear_state = self.state_notice_owner in cleared
        if clear_state:
            self.state_notice_owner = None
        # The reminder text lists waiting appliances, so it is stale now; the
        # next scheduled reminder re-sends it if anything is still waiting.
        return [ClearNotices(state=clear_state, reminder=True)]

    # ------------------------------------------------------------ persistence

    def as_dict(self) -> dict[str, Any]:
        """Serialize persistent state."""
        return {
            "loads": self.loads,
            "last_completed": _iso(self.last_completed),
            "state_notice_owner": (
                self.state_notice_owner.value if self.state_notice_owner else None
            ),
            **{a.value: r.as_dict() for a, r in self.records.items()},
        }

    def load(self, data: dict[str, Any]) -> None:
        """Restore persistent state. Sensor readings start untrusted."""
        for appliance in Appliance:
            self.records[appliance] = ApplianceRecord.from_dict(data.get(appliance))
        loads = data.get("loads", 0)
        self.loads = loads if isinstance(loads, int) and loads >= 0 else 0
        self.last_completed = _parse(data.get("last_completed"))
        try:
            owner = data.get("state_notice_owner")
            self.state_notice_owner = Appliance(owner) if owner else None
        except ValueError:
            self.state_notice_owner = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Only timezone-aware timestamps are ever written; reject anything else.
    return parsed if parsed.tzinfo else None
