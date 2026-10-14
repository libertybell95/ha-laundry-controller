"""Unit tests for the pure laundry state machine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.laundry_controller.state_machine import (
    Announce,
    Appliance,
    ClearNotices,
    FireEvent,
    LaundryStateMachine,
    Notice,
    Phase,
    SendNotice,
)

W = Appliance.WASHER
D = Appliance.DRYER
T0 = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
GRACE = timedelta(seconds=120)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def events(effects) -> list[str]:
    return [e.name for e in effects if isinstance(e, FireEvent)]


def notices(effects) -> list[Notice]:
    return [e.kind for e in effects if isinstance(e, SendNotice)]


def clears(effects) -> list[ClearNotices]:
    return [e for e in effects if isinstance(e, ClearNotices)]


@pytest.fixture
def m() -> LaundryStateMachine:
    """Machine whose sensors have already been trusted as off."""
    machine = LaundryStateMachine(reconnect_grace=GRACE)
    for appliance in Appliance:
        machine.activity(appliance, False, at(-10))
    machine.confirm(at(-5))
    assert machine.washer.trusted and machine.dryer.trusted
    return machine


def test_normal_washer_cycle(m: LaundryStateMachine) -> None:
    fx = m.activity(W, True, at(0))
    assert events(fx) == ["washer_started"]
    assert fx[0].data == {"loads": 1}
    assert m.washer.phase is Phase.RUNNING
    assert m.washer.started_at == at(0)
    assert m.loads == 1

    fx = m.activity(W, False, at(45))
    assert events(fx) == ["washer_finished"]
    assert fx[0].data == {"duration": 2700.0, "dryer_running": False}
    assert notices(fx) == [Notice.WASHER_FINISHED]
    assert m.washer.phase is Phase.DONE
    assert m.washer.finished_at == at(45)
    assert m.washer.last_duration == timedelta(minutes=45)
    assert m.state_of(W) == "wash_done"
    assert m.status == "wash_done"
    assert m.needs_attention


def test_normal_dryer_cycle(m: LaundryStateMachine) -> None:
    fx = m.activity(D, True, at(0))
    assert events(fx) == ["dryer_started"]
    assert m.loads == 0  # loads are counted at the washer
    fx = m.activity(D, False, at(60))
    assert events(fx) == ["dryer_finished"]
    assert notices(fx) == [Notice.DRYER_FINISHED]
    assert any(isinstance(e, Announce) for e in fx)
    assert m.state_of(D) == "dry_done"
    assert m.waiting() == [D]


def test_simultaneous_cycles(m: LaundryStateMachine) -> None:
    m.activity(D, True, at(0))
    m.activity(W, True, at(5))
    assert m.status == "washing_and_drying"
    fx = m.activity(W, False, at(50))
    # Legacy behavior: no phone notification while the dryer is running.
    assert events(fx) == ["washer_finished"]
    assert fx[0].data["dryer_running"] is True
    assert notices(fx) == []
    assert m.status == "wash_done_drying"
    fx = m.activity(D, False, at(60))
    assert notices(fx) == [Notice.DRYER_FINISHED]
    assert m.status == "wash_and_dry_done"


def test_washer_while_dryer_running_option() -> None:
    m = LaundryStateMachine(
        reconnect_grace=timedelta(0), notify_washer_while_dryer_running=True
    )
    m.activity(W, False, at(0))
    m.activity(D, False, at(0))
    m.activity(D, True, at(1))
    m.activity(W, True, at(2))
    assert notices(m.activity(W, False, at(30))) == [Notice.WASHER_FINISHED]


def test_dryer_start_clears_wash_done(m: LaundryStateMachine) -> None:
    m.activity(W, True, at(0))
    m.activity(W, False, at(40))
    assert m.state_notice_owner is W
    fx = m.activity(D, True, at(45))
    assert m.washer.phase is Phase.IDLE
    assert m.dryer.phase is Phase.RUNNING
    assert clears(fx) == [ClearNotices(state=True, reminder=True)]
    assert m.state_notice_owner is None


def test_dryer_start_does_not_touch_running_washer(m: LaundryStateMachine) -> None:
    m.activity(W, True, at(0))
    m.activity(D, True, at(1))
    assert m.washer.phase is Phase.RUNNING


def test_washer_door_after_done(m: LaundryStateMachine) -> None:
    m.activity(W, True, at(0))
    m.activity(W, False, at(40))
    fx = m.door_opened(W, at(41))
    assert m.washer.phase is Phase.IDLE
    assert clears(fx) == [ClearNotices(state=True, reminder=True)]
    assert events(fx) == []
    assert m.last_completed is None


def test_door_ignored_unless_done(m: LaundryStateMachine) -> None:
    assert m.door_opened(W, at(0)) == []
    m.activity(D, True, at(0))
    assert m.door_opened(D, at(1)) == []
    assert m.dryer.phase is Phase.RUNNING


def test_dryer_door_after_done(m: LaundryStateMachine) -> None:
    m.activity(D, True, at(0))
    m.activity(D, False, at(60))
    fx = m.door_opened(D, at(70))
    assert m.dryer.phase is Phase.IDLE
    assert m.last_completed == at(70)
    assert events(fx) == ["laundry_cleared"]
    assert fx[0].data == {"source": "dryer_door", "appliances": ["dryer"]}
    assert clears(fx) == [ClearNotices(state=True, reminder=True)]
    assert not m.needs_attention


def test_dryer_door_keeps_washer_notification(m: LaundryStateMachine) -> None:
    # Dryer finished first, then the washer: the state tag shows the washer.
    m.activity(D, True, at(0))
    m.activity(W, True, at(1))
    m.activity(D, False, at(30))
    m.activity(W, False, at(40))
    assert m.state_notice_owner is W
    fx = m.door_opened(D, at(50))
    assert clears(fx) == [ClearNotices(state=False, reminder=True)]
    assert m.washer.phase is Phase.DONE


def test_hang_dry(m: LaundryStateMachine) -> None:
    m.activity(W, True, at(0))
    m.activity(W, False, at(40))
    fx = m.hang_dry(at(41))
    assert m.washer.phase is Phase.IDLE
    assert events(fx) == ["laundry_cleared"]
    assert fx[0].data["source"] == "hang_dry"
    assert clears(fx) == [ClearNotices(state=True, reminder=True)]


def test_hang_dry_never_touches_running_appliances(m: LaundryStateMachine) -> None:
    m.activity(W, True, at(0))
    m.activity(D, True, at(0))
    assert m.hang_dry(at(1)) == []
    assert m.washer.phase is Phase.RUNNING
    assert m.dryer.phase is Phase.RUNNING


def test_mark_done(m: LaundryStateMachine) -> None:
    m.activity(W, True, at(0))
    m.activity(W, False, at(40))
    m.activity(D, True, at(41))
    m.activity(D, False, at(90))
    m.activity(W, True, at(95))
    m.activity(W, False, at(130))
    fx = m.mark_done(at(140), "notification")
    assert m.washer.phase is Phase.IDLE
    assert m.dryer.phase is Phase.IDLE
    assert events(fx) == ["laundry_cleared"]
    assert fx[0].data == {"source": "notification", "appliances": ["washer", "dryer"]}
    assert m.last_completed == at(140)
    assert clears(fx) == [ClearNotices(state=True, reminder=True)]


def test_mark_done_never_resets_running(m: LaundryStateMachine) -> None:
    m.activity(D, True, at(0))
    m.activity(D, False, at(50))
    m.activity(W, True, at(55))
    fx = m.mark_done(at(60), "button")
    assert m.washer.phase is Phase.RUNNING
    assert m.dryer.phase is Phase.IDLE
    assert fx[0].data["appliances"] == ["dryer"]
    # The running washer still finishes normally afterwards.
    assert events(m.activity(W, False, at(90))) == ["washer_finished"]


def test_mark_done_with_nothing_waiting(m: LaundryStateMachine) -> None:
    fx = m.mark_done(at(0), "button")
    assert events(fx) == []
    assert m.last_completed is None
    assert clears(fx) == [ClearNotices(state=True, reminder=True)]


def test_repeated_identical_events(m: LaundryStateMachine) -> None:
    m.activity(W, True, at(0))
    assert m.activity(W, True, at(1)) == []
    assert m.activity(W, True, at(2)) == []
    assert m.loads == 1
    m.activity(W, False, at(40))
    assert m.activity(W, False, at(41)) == []
    assert m.washer.finished_at == at(40)


def test_sensor_unavailable_mid_cycle_and_back_on(m: LaundryStateMachine) -> None:
    m.activity(W, True, at(0))
    assert m.activity(W, None, at(10)) == []
    assert m.activity(W, True, at(11)) == []
    assert m.confirm(at(11) + GRACE) == []
    assert m.loads == 1
    assert m.washer.phase is Phase.RUNNING
    # Normal finish afterwards
    assert events(m.activity(W, False, at(40))) == ["washer_finished"]


def test_unavailable_then_off_is_not_an_immediate_finish(
    m: LaundryStateMachine,
) -> None:
    m.activity(D, True, at(0))
    m.activity(D, None, at(10))
    assert m.activity(D, False, at(11)) == []
    assert m.dryer.phase is Phase.RUNNING
    assert m.next_confirm_at() == at(11) + GRACE
    # Comes back on within the grace period: the cycle simply continues.
    assert m.activity(D, True, at(12)) == []
    assert m.confirm(at(12) + GRACE) == []
    assert m.dryer.phase is Phase.RUNNING


def test_unavailable_then_off_confirmed_finishes(m: LaundryStateMachine) -> None:
    m.activity(D, True, at(0))
    m.activity(D, None, at(10))
    m.activity(D, False, at(11))
    assert m.confirm(at(11)) == []  # too early
    fx = m.confirm(at(11) + GRACE)
    assert events(fx) == ["dryer_finished"]
    assert m.dryer.finished_at == at(11)  # time the reading was observed


def test_reconnect_without_cycle_is_ignored(m: LaundryStateMachine) -> None:
    m.activity(W, None, at(0))
    assert m.activity(W, False, at(1)) == []
    assert m.confirm(at(1) + GRACE) == []
    assert m.washer.phase is Phase.IDLE
    assert m.loads == 0


def test_reconnect_on_while_idle_starts_after_grace(m: LaundryStateMachine) -> None:
    m.activity(W, None, at(0))
    m.activity(W, True, at(1))
    assert m.loads == 0
    fx = m.confirm(at(1) + GRACE)
    assert events(fx) == ["washer_started"]
    assert m.loads == 1
    assert m.washer.started_at == at(1)


def test_brief_phantom_on_at_startup_ignored() -> None:
    m = LaundryStateMachine(reconnect_grace=GRACE)
    m.activity(W, True, at(0))
    m.activity(W, False, at(0.5))
    assert m.confirm(at(5)) == []
    assert m.loads == 0
    assert m.washer.phase is Phase.IDLE


def test_untrusted_repeat_keeps_timestamp() -> None:
    m = LaundryStateMachine(reconnect_grace=GRACE)
    m.activity(W, True, at(0))
    m.activity(W, True, at(1))
    assert m.next_confirm_at() == at(0) + GRACE


def test_zero_grace_acts_immediately() -> None:
    m = LaundryStateMachine(reconnect_grace=timedelta(0))
    assert events(m.activity(W, True, at(0))) == ["washer_started"]


def test_waiting_excludes_unconfirmed(m: LaundryStateMachine) -> None:
    m.activity(D, True, at(0))
    m.activity(D, False, at(30))
    m.activity(D, None, at(31))
    m.activity(D, True, at(32))  # possibly a new cycle, unconfirmed
    assert m.waiting() == []
    assert m.needs_attention


def test_restart_during_active_cycle(m: LaundryStateMachine) -> None:
    m.activity(W, True, at(0))
    restored = LaundryStateMachine(reconnect_grace=GRACE)
    restored.load(m.as_dict())
    assert restored.washer.phase is Phase.RUNNING
    assert restored.loads == 1
    # Sensor still on after restart: no new load once confirmed.
    restored.activity(W, True, at(5))
    assert restored.confirm(at(5) + GRACE) == []
    assert restored.loads == 1
    assert events(restored.activity(W, False, at(40))) == ["washer_finished"]
    assert restored.washer.last_duration == timedelta(minutes=40)


def test_restart_cycle_finished_while_down(m: LaundryStateMachine) -> None:
    m.activity(D, True, at(0))
    restored = LaundryStateMachine(reconnect_grace=GRACE)
    restored.load(m.as_dict())
    restored.activity(D, False, at(90))
    assert restored.dryer.phase is Phase.RUNNING
    assert events(restored.confirm(at(90) + GRACE)) == ["dryer_finished"]


def test_restart_with_completed_laundry_pending(m: LaundryStateMachine) -> None:
    m.activity(D, True, at(0))
    m.activity(D, False, at(60))
    restored = LaundryStateMachine(reconnect_grace=GRACE)
    restored.load(m.as_dict())
    assert restored.dryer.phase is Phase.DONE
    assert restored.dryer.finished_at == at(60)
    assert restored.state_notice_owner is D
    restored.activity(D, False, at(100))
    assert restored.confirm(at(100) + GRACE) == []
    assert restored.waiting() == [D]


def test_reset_resyncs_with_trusted_readings(m: LaundryStateMachine) -> None:
    m.activity(D, True, at(0))
    m.activity(D, False, at(50))
    m.activity(W, True, at(55))
    m.reset(at(60))
    assert m.dryer.phase is Phase.IDLE
    assert m.washer.phase is Phase.RUNNING
    assert m.loads == 1


def test_load_tolerates_garbage() -> None:
    m = LaundryStateMachine()
    m.load(
        {
            "loads": -3,
            "washer": {"phase": "bogus", "started_at": "nope"},
            "dryer": {"finished_at": "2026-01-01T00:00:00"},  # naive -> rejected
            "state_notice_owner": "fridge",
        }
    )
    assert m.loads == 0
    assert m.washer.phase is Phase.IDLE
    assert m.dryer.finished_at is None
    assert m.state_notice_owner is None
