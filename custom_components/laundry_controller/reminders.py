"""Reminder scheduling (pure functions, no Home Assistant imports).

A waiting appliance becomes due for a reminder one interval after it
finished, then one interval after each reminder sent. Reminders that fall in
quiet hours are moved to the start of the next allowed window. Because only
the *next* due time is ever scheduled, a restart can produce at most one
catch-up reminder, never a backlog.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, tzinfo

from .state_machine import Appliance, LaundryStateMachine


def parse_time(value: str | time) -> time:
    """Parse "HH:MM[:SS]" into a time."""
    if isinstance(value, time):
        return value
    return time.fromisoformat(value)


def in_window(local: datetime, start: time, end: time) -> bool:
    """Return True if a local datetime is inside the allowed window.

    ``start == end`` means reminders are allowed all day. A window whose end
    is before its start wraps past midnight (e.g. 20:00-02:00).
    """
    if start == end:
        return True
    now = local.time()
    if start < end:
        return start <= now < end
    return now >= start or now < end


def next_window_start(local: datetime, start: time, end: time) -> datetime:
    """Return ``local`` if allowed, else the next window start (aware, local tz)."""
    if in_window(local, start, end):
        return local
    candidate = datetime.combine(local.date(), start, tzinfo=local.tzinfo)
    if candidate <= local:
        candidate = datetime.combine(
            local.date() + timedelta(days=1), start, tzinfo=local.tzinfo
        )
    return candidate


def due_at(
    machine: LaundryStateMachine,
    appliance: Appliance,
    now: datetime,
    interval: timedelta,
) -> datetime:
    """When an appliance is next due for a reminder (ignoring quiet hours)."""
    record = machine.records[appliance]
    base = record.last_reminded_at or record.finished_at or now
    return base + interval


def next_reminder_at(
    machine: LaundryStateMachine,
    now: datetime,
    *,
    interval: timedelta,
    start: time,
    end: time,
    tz: tzinfo,
) -> datetime | None:
    """Next time a reminder should be sent, or None if nothing is waiting."""
    waiting = machine.waiting()
    if not waiting:
        return None
    due = max(min(due_at(machine, a, now, interval) for a in waiting), now)
    return next_window_start(due.astimezone(tz), start, end)


def is_overdue(
    machine: LaundryStateMachine,
    appliance: Appliance,
    now: datetime,
    overdue_after: timedelta,
) -> bool:
    """Return True if an appliance's laundry has waited longer than allowed."""
    finished = machine.records[appliance].finished_at
    return finished is not None and now - finished > overdue_after
