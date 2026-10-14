"""Unit tests for reminder scheduling."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from custom_components.laundry_controller.notifications import (
    build_reminder,
    format_age,
)
from custom_components.laundry_controller.reminders import (
    in_window,
    is_overdue,
    next_reminder_at,
    next_window_start,
    parse_time,
)
from custom_components.laundry_controller.state_machine import (
    Appliance,
    LaundryStateMachine,
)

TZ = ZoneInfo("America/New_York")
START = time(8)
END = time(22)
INTERVAL = timedelta(minutes=15)


def local(hour: int, minute: int = 0, day: int = 14) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def finished_dryer(finished: datetime) -> LaundryStateMachine:
    m = LaundryStateMachine(reconnect_grace=timedelta(0))
    m.activity(Appliance.DRYER, True, finished - timedelta(hours=1))
    m.activity(Appliance.DRYER, False, finished)
    return m


def test_window() -> None:
    assert in_window(local(8), START, END)
    assert in_window(local(21, 59), START, END)
    assert not in_window(local(22), START, END)
    assert not in_window(local(7, 59), START, END)
    # Wrapping window 20:00-02:00
    assert in_window(local(23), time(20), time(2))
    assert in_window(local(1), time(20), time(2))
    assert not in_window(local(12), time(20), time(2))
    # Equal start/end = all day
    assert in_window(local(3), time(0), time(0))


def test_next_window_start() -> None:
    assert next_window_start(local(10), START, END) == local(10)
    assert next_window_start(local(23), START, END) == local(8, day=15)
    assert next_window_start(local(6), START, END) == local(8)


def test_first_reminder_one_interval_after_finish() -> None:
    m = finished_dryer(local(12).astimezone(UTC))
    nxt = next_reminder_at(
        m, local(12, 1), interval=INTERVAL, start=START, end=END, tz=TZ
    )
    assert nxt == local(12, 15)


def test_reminder_repeats_after_last_reminder() -> None:
    m = finished_dryer(local(12))
    m.dryer.last_reminded_at = local(12, 15)
    nxt = next_reminder_at(
        m, local(12, 16), interval=INTERVAL, start=START, end=END, tz=TZ
    )
    assert nxt == local(12, 30)


def test_quiet_hours_defer_to_window_start() -> None:
    m = finished_dryer(local(21, 50))
    nxt = next_reminder_at(
        m, local(21, 51), interval=INTERVAL, start=START, end=END, tz=TZ
    )
    assert nxt == local(8, day=15)


def test_no_backlog_after_long_downtime() -> None:
    m = finished_dryer(local(9))
    now = local(15)
    nxt = next_reminder_at(m, now, interval=INTERVAL, start=START, end=END, tz=TZ)
    assert nxt == now  # exactly one catch-up reminder, right away


def test_nothing_waiting() -> None:
    m = LaundryStateMachine()
    assert (
        next_reminder_at(m, local(12), interval=INTERVAL, start=START, end=END, tz=TZ)
        is None
    )


def test_overdue_and_message() -> None:
    m = finished_dryer(local(12))
    m.activity(Appliance.WASHER, True, local(12, 10))
    m.activity(Appliance.WASHER, False, local(13, 0))
    now = local(13, 20)
    assert is_overdue(m, Appliance.DRYER, now, timedelta(minutes=60))
    assert not is_overdue(m, Appliance.WASHER, now, timedelta(minutes=60))
    msg = build_reminder(
        m, [Appliance.WASHER, Appliance.DRYER], now, timedelta(minutes=60), "abc"
    )
    assert msg.title == "OVERDUE: Laundry!"
    assert msg.importance == "high"
    assert msg.message == "Washer finished 20 min ago. Dryer finished 1 h 20 min ago."
    assert msg.actions == (("LAUNDRY_MARK_DONE:abc", "Mark as Done"),)
    not_overdue = build_reminder(
        m, [Appliance.WASHER], now, timedelta(minutes=60), "abc"
    )
    assert not_overdue.title == "Laundry Reminder"
    assert not_overdue.importance == "default"


def test_format_age_and_parse_time() -> None:
    assert format_age(timedelta(seconds=30)) == "less than a minute"
    assert format_age(timedelta(minutes=5)) == "5 min"
    assert format_age(timedelta(hours=2)) == "2 h"
    assert parse_time("08:30:00") == time(8, 30)
