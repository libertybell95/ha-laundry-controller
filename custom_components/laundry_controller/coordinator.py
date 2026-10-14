"""Laundry controller: connects the state machine to Home Assistant."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ACTION_HANG_DRY,
    CONF_DRYER_DOOR,
    CONF_DRYER_RUNNING,
    CONF_NOTIFY_WASHER_WHILE_DRYER_RUNNING,
    CONF_OVERDUE_AFTER,
    CONF_RECIPIENTS,
    CONF_RECONNECT_GRACE,
    CONF_REMINDER_END,
    CONF_REMINDER_INTERVAL,
    CONF_REMINDER_START,
    CONF_WASHER_DOOR,
    CONF_WASHER_RUNNING,
    DEFAULT_OPTIONS,
    DOMAIN,
    MOBILE_APP_ACTION_EVENT,
    SAVE_DELAY,
    STORAGE_VERSION,
)
from .notifications import (
    Notifier,
    PhoneMessage,
    build_finished,
    build_reminder,
    parse_action,
    reminder_tag,
    state_tag,
)
from .reminders import in_window, is_overdue, next_reminder_at, parse_time
from .state_machine import (
    Announce,
    Appliance,
    ClearNotices,
    Effect,
    FireEvent,
    LaundryStateMachine,
    Phase,
    SendNotice,
)
from .tts import Announcer

_LOGGER = logging.getLogger(__name__)

type LaundryConfigEntry = ConfigEntry[LaundryController]

ACTIVITY_ROLES = {
    CONF_WASHER_RUNNING: Appliance.WASHER,
    CONF_DRYER_RUNNING: Appliance.DRYER,
}
DOOR_ROLES = {CONF_WASHER_DOOR: Appliance.WASHER, CONF_DRYER_DOOR: Appliance.DRYER}


def _reading(state: State | None) -> bool | None:
    """Convert a binary sensor state to on/off/None (unknown or unavailable)."""
    if state is None or state.state not in (STATE_ON, STATE_OFF):
        return None
    return state.state == STATE_ON


class LaundryController:
    """Owns the state machine, persistence, timers and side effects."""

    def __init__(self, hass: HomeAssistant, entry: LaundryConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.options: dict[str, Any] = {**DEFAULT_OPTIONS, **entry.options}
        self.machine = LaundryStateMachine(
            reconnect_grace=timedelta(seconds=self.options[CONF_RECONNECT_GRACE]),
            notify_washer_while_dryer_running=self.options[
                CONF_NOTIFY_WASHER_WHILE_DRYER_RUNNING
            ],
        )
        self.reminders_enabled = True
        self.tts_enabled = True
        self.notifier = Notifier(
            hass, entry.entry_id, entry.title, self.options[CONF_RECIPIENTS]
        )
        self.announcer = Announcer(hass, entry.entry_id, entry.title, self.options)
        self.next_reminder: datetime | None = None
        self._activity = {entry.data[k]: a for k, a in ACTIVITY_ROLES.items()}
        self._doors = {entry.data[k]: a for k, a in DOOR_ROLES.items()}
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._confirm_at: datetime | None = None
        self._confirm_unsub: CALLBACK_TYPE | None = None
        self._reminder_unsub: CALLBACK_TYPE | None = None
        # Notification sends/clears run in order, one batch at a time.
        self._notify_lock = asyncio.Lock()
        self._snapshot: dict[str, Any] = {}

    # -------------------------------------------------------------- lifecycle

    async def async_setup(self) -> None:
        """Restore state, subscribe to sensors and reconcile."""
        if stored := await self._store.async_load():
            self.machine.load(stored.get("machine", {}))
            self.reminders_enabled = bool(stored.get("reminders_enabled", True))
            self.tts_enabled = bool(stored.get("tts_enabled", True))
        self._snapshot = self._data()

        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [*self._activity, *self._doors], self._handle_state_event
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen(MOBILE_APP_ACTION_EVENT, self._handle_action)
        )

        # Reconcile restored state with current readings. Readings start
        # untrusted; one that has already been stable for the grace period
        # (e.g. after an options reload) is confirmed right away, while one
        # that only just appeared (Home Assistant start-up) must prove stable.
        now = dt_util.utcnow()
        effects: list[Effect] = []
        for entity_id, appliance in self._activity.items():
            state = self.hass.states.get(entity_id)
            since = min(state.last_changed, now) if state else now
            effects += self.machine.activity(appliance, _reading(state), since)
        effects += self.machine.confirm(now)
        self._process(effects)

    async def async_shutdown(self) -> None:
        """Unsubscribe everything and flush state to disk."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_confirm()
        self._cancel_reminder()
        await self._store.async_save(self._data())

    # -------------------------------------------------------------- listeners

    @callback
    def async_add_listener(self, update: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Register an entity update callback."""
        self._listeners.append(update)

        @callback
        def remove() -> None:
            self._listeners.remove(update)

        return remove

    # ---------------------------------------------------------------- inputs

    @callback
    def _handle_state_event(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        new_state = event.data["new_state"]
        now = dt_util.utcnow()
        if (appliance := self._activity.get(entity_id)) is not None:
            self._process(self.machine.activity(appliance, _reading(new_state), now))
            return
        if (appliance := self._doors.get(entity_id)) is not None:
            old_state = event.data["old_state"]
            # Only a genuine closed -> open transition counts; a sensor that
            # reconnects reporting "open" is ignored.
            if (
                old_state is not None
                and new_state is not None
                and old_state.state == STATE_OFF
                and new_state.state == STATE_ON
            ):
                self._process(self.machine.door_opened(appliance, now))

    @callback
    def _handle_action(self, event: Event) -> None:
        parsed = parse_action(event.data.get("action") or event.data.get("actionName"))
        if parsed is None or parsed[1] != self.entry.entry_id:
            return
        if parsed[0] == ACTION_HANG_DRY:
            self.hang_dry()
        else:
            self.mark_done("notification")

    # ------------------------------------------------------------ public API

    @callback
    def hang_dry(self) -> None:
        """Acknowledge the washer load as hung to dry."""
        self._process(self.machine.hang_dry(dt_util.utcnow()))

    @callback
    def mark_done(self, source: str) -> None:
        """Acknowledge all finished laundry."""
        self._process(self.machine.mark_done(dt_util.utcnow(), source))

    @callback
    def reset(self) -> None:
        """Reset finished states and re-sync with the sensors."""
        self._process(self.machine.reset(dt_util.utcnow()))

    @callback
    def set_loads(self, loads: int) -> None:
        """Set the load counter."""
        self.machine.set_loads(loads)
        self._process([])

    @callback
    def set_last_completed(self, when: datetime | None) -> None:
        """Set the last completed timestamp."""
        self.machine.set_last_completed(dt_util.as_utc(when) if when else None)
        self._process([])

    @callback
    def set_reminders_enabled(self, enabled: bool) -> None:
        """Enable or disable reminders."""
        self.reminders_enabled = enabled
        self._process([])

    @callback
    def set_tts_enabled(self, enabled: bool) -> None:
        """Enable or disable announcements."""
        self.tts_enabled = enabled
        self._process([])

    # ---------------------------------------------------------- side effects

    @callback
    def _process(self, effects: list[Effect]) -> None:
        """Perform effects, persist, update entities and re-sync timers."""
        ops: list[tuple[str, PhoneMessage | str]] = []
        for effect in effects:
            if isinstance(effect, FireEvent):
                self.hass.bus.async_fire(
                    f"{DOMAIN}_{effect.name}",
                    {
                        "config_entry_id": self.entry.entry_id,
                        "name": self.entry.title,
                        **effect.data,
                    },
                )
            elif isinstance(effect, SendNotice):
                # Built now so the text reflects the state at transition time.
                ops.append(
                    (
                        "send",
                        build_finished(effect.kind, self.machine, self.entry.entry_id),
                    )
                )
            elif isinstance(effect, ClearNotices):
                if effect.state:
                    ops.append(("clear", state_tag(self.entry.entry_id)))
                if effect.reminder:
                    ops.append(("clear", reminder_tag(self.entry.entry_id)))
            elif isinstance(effect, Announce) and self.tts_enabled:
                self._background(self.announcer.async_announce(), "announce")
        if ops and self.notifier.recipients:
            self._background(self._async_run_ops(ops), "notify")

        data = self._data()
        if data != self._snapshot:
            self._snapshot = data
            self._store.async_delay_save(self._data, SAVE_DELAY)
            for update in list(self._listeners):
                update()
        self._sync_timers()

    def _background(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        self.entry.async_create_background_task(
            self.hass, coro, f"{DOMAIN}_{self.entry.entry_id}_{name}"
        )

    async def _async_run_ops(self, ops: list[tuple[str, PhoneMessage | str]]) -> None:
        async with self._notify_lock:
            for kind, arg in ops:
                if kind == "send":
                    assert isinstance(arg, PhoneMessage)
                    await self.notifier.async_send(arg)
                else:
                    assert isinstance(arg, str)
                    await self.notifier.async_clear(arg)

    @callback
    def _data(self) -> dict[str, Any]:
        return {
            "machine": self.machine.as_dict(),
            "reminders_enabled": self.reminders_enabled,
            "tts_enabled": self.tts_enabled,
        }

    # ----------------------------------------------------------------- timers

    @callback
    def _sync_timers(self) -> None:
        confirm_at = self.machine.next_confirm_at()
        if confirm_at != self._confirm_at:
            self._cancel_confirm()
            if confirm_at is not None:
                self._confirm_at = confirm_at
                self._confirm_unsub = async_track_point_in_utc_time(
                    self.hass, self._on_confirm, confirm_at
                )

        reminder_at = self._compute_next_reminder()
        if reminder_at != self.next_reminder:
            self._cancel_reminder()
            if reminder_at is not None:
                self.next_reminder = reminder_at
                self._reminder_unsub = async_track_point_in_utc_time(
                    self.hass, self._on_reminder, reminder_at
                )
            for update in list(self._listeners):
                update()

    def _compute_next_reminder(self) -> datetime | None:
        if not self.reminders_enabled or not self.notifier.recipients:
            return None
        return next_reminder_at(
            self.machine,
            dt_util.utcnow(),
            interval=timedelta(minutes=self.options[CONF_REMINDER_INTERVAL]),
            start=parse_time(self.options[CONF_REMINDER_START]),
            end=parse_time(self.options[CONF_REMINDER_END]),
            tz=dt_util.get_default_time_zone(),
        )

    @callback
    def _cancel_confirm(self) -> None:
        if self._confirm_unsub:
            self._confirm_unsub()
        self._confirm_unsub = None
        self._confirm_at = None

    @callback
    def _cancel_reminder(self) -> None:
        if self._reminder_unsub:
            self._reminder_unsub()
        self._reminder_unsub = None
        self.next_reminder = None

    @callback
    def _on_confirm(self, _: datetime) -> None:
        self._confirm_unsub = None
        self._confirm_at = None
        self._process(self.machine.confirm(dt_util.utcnow()))

    @callback
    def _on_reminder(self, _: datetime) -> None:
        self._reminder_unsub = None
        self.next_reminder = None
        now = dt_util.utcnow()
        waiting = self.machine.waiting()
        start = parse_time(self.options[CONF_REMINDER_START])
        end = parse_time(self.options[CONF_REMINDER_END])
        if (
            waiting
            and self.reminders_enabled
            and in_window(dt_util.as_local(now), start, end)
        ):
            msg = build_reminder(
                self.machine,
                waiting,
                now,
                timedelta(minutes=self.options[CONF_OVERDUE_AFTER]),
                self.entry.entry_id,
            )
            for appliance in waiting:
                self.machine.records[appliance].last_reminded_at = now
            self._background(self._async_run_ops([("send", msg)]), "reminder")
        self._process([])

    # ---------------------------------------------------------------- queries

    def is_overdue(self, appliance: Appliance) -> bool:
        """Return True if the appliance's finished laundry is overdue."""
        return self.machine.records[appliance].phase is Phase.DONE and is_overdue(
            self.machine,
            appliance,
            dt_util.utcnow(),
            timedelta(minutes=self.options[CONF_OVERDUE_AFTER]),
        )
