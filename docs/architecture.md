# Architecture

Laundry Controller is a plain Home Assistant custom integration. It runs in
Home Assistant's event loop, has no external dependencies, no polling, and no
threads.

## Modules

| Module | Responsibility |
| --- | --- |
| `state_machine.py` | Washer/dryer phases, load counter, sensor trust policy, persistence format. **No Home Assistant imports**, every method is synchronous and returns a list of side effects. |
| `reminders.py` | Pure reminder scheduling: allowed window, next due time, overdue check. |
| `coordinator.py` | `LaundryController`: subscribes to sensors and phone actions, runs the state machine, performs side effects, persists state, owns timers. |
| `notifications.py` | Notification text/actions (pure functions) and `Notifier` (delivery, failure handling, repair issues). |
| `tts.py` | `Announcer`: On-Air check, random message, announcement script call. |
| `services.py` | Integration actions (`laundry_controller.*`). |
| `config_flow.py` | Setup, reconfigure and options flows. |
| `sensor.py`, `binary_sensor.py`, `switch.py`, `button.py`, `entity.py` | Entities; they only read controller state. |
| `diagnostics.py` | Config-entry diagnostics (recipients and speaker id redacted). |

## Data flow

```text
 state_changed (running sensors, doors)  ─┐
 mobile_app_notification_action          ─┤
 button / switch / actions               ─┼─► LaundryController ─► LaundryStateMachine
 confirm + reminder timers               ─┘          │                    │
                                                     │◄── effects ────────┘
                                                     ├─► bus events (laundry_controller_*)
                                                     ├─► Notifier (ordered, background)
                                                     ├─► Announcer (background)
                                                     ├─► Store (.storage, delayed save)
                                                     ├─► entity updates
                                                     └─► re-sync timers
```

## Serialization

All inputs are handled in `@callback` functions on the event loop. Each one
calls a synchronous state machine method and applies the result without any
`await` in between, so two inputs can never interleave and corrupt state.
Slow work — notification delivery and the announcement script — runs in
config-entry background tasks *after* the transition is committed, so a slow
or failing phone/speaker can never delay or undo a transition.

Notification batches go through a FIFO `asyncio.Lock`, so a "finished" message
and the "clear" that follows it are delivered in order. Announcements run
independently because the script may take 30 s or more.

## Sensor trust policy (reconnects and restarts)

Each running sensor reading is either *trusted* or *untrusted*:

* A change between two known values (`on → off`, `off → on`) is trusted and
  acted on immediately.
* A reading that follows `unknown`/`unavailable`, or the first reading after
  setup, is untrusted. It must stay unchanged for the **reconnect grace period**
  (default 120 s) before it is reconciled against the appliance phase:
  * reading `on`, appliance not running → cycle starts (load counted; start time
    is when the reading first appeared);
  * reading `off`, appliance running → cycle finishes (finish time is when the
    reading first appeared);
  * otherwise nothing happens.
* On setup, a reading whose `last_changed` is already older than the grace
  period is confirmed immediately (e.g. after an options reload). At Home
  Assistant start-up states are fresh, so they wait out the grace period.

Consequences:

| Scenario | Result |
| --- | --- |
| Running → `unavailable` → `on` | Cycle continues; no new load. |
| Running → `unavailable` → `off` → `on` within grace | Cycle continues. |
| Running → `unavailable` → `off` (stays off) | Finishes after the grace period. |
| Idle → `unavailable` → `off` | Nothing. |
| Restart while running, sensor still `on` | Cycle continues; no new load. |
| Restart while running, sensor now `off` | Finishes after the grace period (cycle ended while Home Assistant was down). |
| Restart while idle, sensor now `on` (and stays on) | New cycle, counted once. |
| Brief `on` blip at start-up | Ignored. |

Door sensors only count a genuine `off → on` (closed → open). A door sensor that
reconnects reporting "open" is ignored.

## State machine

| Input | Washer | Dryer |
| --- | --- | --- |
| running sensor on | → Washing, load +1, `washer_started` | → Drying, `dryer_started`; washer Wash Done → Idle |
| running sensor off | → Wash Done, `washer_finished`, notify unless dryer running | → Dry Done, `dryer_finished`, notify, announce |
| door opened | Wash Done → Idle | Dry Done → Idle, last completed, `laundry_cleared` |
| Hang Dry | Wash Done → Idle, `laundry_cleared` | — |
| Mark Done | Wash Done → Idle | Dry Done → Idle; last completed; `laundry_cleared` |
| Reset | → Washing if sensor trusted on, else Idle | same |

Running appliances are never reset by Hang Dry or Mark Done.

The controller remembers which appliance's "finished" notification occupies
the *state* notification tag, so clearing one appliance doesn't remove a
notification about the other.

## Persistence

State lives in `.storage/laundry_controller.<entry_id>` (Home Assistant
`Store`, version 1). Saved with a 1 s delay after every change, and on unload
and shutdown. Persisted: phase, start/finish time, last duration and last
reminder time for each appliance; load count; last completed; which appliance
owns the state notification; reminder and announcement switch states.
Timestamps are stored as timezone-aware ISO-8601 in UTC; reminder windows use
Home Assistant's configured time zone.

Sensor readings are *not* persisted; after a restart they start untrusted.

## Reminders

Only the single next reminder time is scheduled
(`async_track_point_in_utc_time`); it is recomputed after every change:

* due = (last reminder or finish time) + interval, per waiting appliance;
  earliest wins;
* never earlier than now (so a restart produces at most one catch-up reminder);
* moved to the start of the next allowed window if in quiet hours.

When it fires, one notification lists every waiting appliance and they are
all marked reminded. Unconfirmed appliances (pending sensor confirmation) are
excluded until confirmed.

## Multiple instances

Each config entry has its own state file, entities, device, notification tags
(`laundry_controller_<entry_id>_state` / `_reminder`) and action identifiers
(`LAUNDRY_MARK_DONE:<entry_id>`), so instances cannot acknowledge each other's
laundry. Actions require `config_entry_id` when more than one is loaded.

## Failure handling

* Missing notify service or script: logged, a repair issue is raised, the
  transition still happens. The issue clears itself once delivery works again.
* Service call errors or timeouts (30 s for notifications; light duration +
  120 s for the script): logged and recorded for diagnostics.
* Non-mobile-app notify services receive only title and message (no tags,
  actions, or "clear_notification" texts).
* If platform setup fails, `async_on_unload` still shuts the controller down so
  no listener or timer leaks.
