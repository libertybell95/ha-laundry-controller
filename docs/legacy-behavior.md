# Legacy Node-RED behavior

This document records what the original Node-RED flow
([`references/node-red-flow.json`](../references/node-red-flow.json), tab
"Laundry Controller", 45 nodes, `node-red-contrib-home-assistant-websocket`
0.80.3) actually does. It is the source of truth used when building the
integration and the migration checklist at the bottom.

## 1. Inventory

### Input entities (state-changed triggers)

| Role | Entity | Trigger settings |
| --- | --- | --- |
| Washer running | `binary_sensor.washer_activity_washer_running` | every state change, *no* filtering of `unknown`/`unavailable` (old or new) |
| Dryer running | `binary_sensor.dryer_activity_dryer_running` | same |
| Washer door | `binary_sensor.washer_door` | same |
| Dryer door | `binary_sensor.dryer_door` | same |
| Phone actions | event `mobile_app_notification_action` | all actions, from any device |

### Helpers written by the flow

| Helper | Written values |
| --- | --- |
| `input_select.washer_state` | `Idle`, `Washing`, `Wash Done` |
| `input_select.dryer_state` | `Idle`, `Drying`, `Dry Done` |
| `input_boolean.dryer_alert` | on at dryer finish, off at dryer door open |
| `input_datetime.laundry_last_done` | local time string at dryer door open |
| `counter.laundry_loads` | `counter.increment` at washer start |

### Entities read but not written

| Entity | Use |
| --- | --- |
| `sensor.laundry_status` | Template sensor defined outside the flow. Its text is the body of the "dryer finished" and reminder notifications. Fallback when unavailable: `Washer: <state> \| Dryer: <state>`. |
| `switch.on_air_sign_2_josh_on_air_led_power_2` | TTS only proceeds when this is exactly `off`. |

### Services called

| Service | When |
| --- | --- |
| `input_select.select_option` | every appliance transition |
| `counter.increment` | washer start |
| `input_boolean.turn_on/off` | dryer alert |
| `input_datetime.set_datetime` | dryer door open after Dry Done |
| `script.laundry_mark_done` | "Mark as Done" phone action (contents of this script are **not** in the flow) |
| `notify.mobile_app_pixel_bell`, `notify.mobile_app_ashers_phone` | phone notifications |
| `script.smart_speaker_tts_with_light` | dryer finished announcement |

### Timers

* `Load Laundry Config` inject: once, 1 s after deploy; writes config into flow context.
* `Reminder Check`: every 900 s (15 min), wall-clock based, not tied to completion time.

### Configuration constants

* Phone tags: state = `laundry_state`, reminder = `laundry_reminder`.
* Reminder window: `startHour = 8`, `endHour = 22` (hour granularity, `hour < 8 || hour >= 22` is quiet).
* Overdue: 60 minutes.
* TTS: speaker device id `09aa5bd9cb63149e10f689141db50016`, language `en-GB`,
  voice `RyanNeural`, volume `0.7`, LED colour `[0, 80, 255]`, brightness `70`,
  max light duration `30`, ten random "dryer finished" messages.

## 2. Behavior by trigger

### Washer running sensor

* `→ on`: if washer state is not `Washing` → set `Washing`, **increment load counter**,
  emit `washer_started` (no consumer: neither phone nor TTS reacts).
  Already `Washing` → ignored.
* `→ off`: if previous sensor state was `on` **or** washer state is `Washing` →
  set `Wash Done`; emit `washer_finished`, or
  `washer_finished_while_dryer_running` when dryer state is `Drying`.
  * `washer_finished` → phone: title "Laundry", "Washer finished! Move clothes to
    the dryer.", tag `laundry_state`, action **Hang Dry (Done)** (`LAUNDRY_HANG_DRY`).
  * `washer_finished_while_dryer_running` → **no notification** (phone router has no
    branch for it). This is the "distinct handling" when the dryer is running.
* any other state (`unavailable`, `unknown`) → ignored.

### Dryer running sensor

* `→ on`: set `Drying` if not already; if washer is `Wash Done` → washer `Idle`.
  Always emits `dryer_started` (even if it was already `Drying`), no consumer.
* `→ off`: if previous sensor state `on` or dryer state `Drying` → `Dry Done`,
  `dryer_alert` on, emit `dryer_finished` with the `sensor.laundry_status` text.
  * Phone: title "Laundry", status text, tag `laundry_state`, action **Mark as Done**.
  * TTS: random message → On-Air check → `script.smart_speaker_tts_with_light`.

### Washer door

* `→ on`/`open` while washer is `Wash Done` → washer `Idle`, clear `laundry_state`
  notification. Otherwise ignored.

### Dryer door

* `→ on`/`open` while dryer is `Dry Done` → dryer `Idle`, `dryer_alert` off,
  `laundry_last_done` = now, clear **both** tags. Otherwise ignored.

### Phone actions

* `LAUNDRY_HANG_DRY` → washer `Idle` (unconditionally), clear `laundry_state`.
* `LAUNDRY_MARK_DONE` → shadow both appliances `Idle` (unconditionally), call
  `script.laundry_mark_done`, clear both tags.

### Reminder timer (every 15 min)

* Skip when disabled or outside 08:00–22:00.
* If washer is `Wash Done` or dryer is `Dry Done`: send one notification with tag
  `laundry_reminder`, action **Mark as Done**, body = status text.
  * If either helper's `last_changed` is more than 60 min ago → title
    "OVERDUE: Laundry!", `importance: high`; else "Laundry Reminder",
    `importance: default`.

### TTS

* Only `dryer_finished` is announced.
* The On-Air gate is an `api-current-state` node that passes only when the
  hard-coded switch is `off`; any other state (`on`, `unavailable`, missing)
  silently suppresses the announcement. The `silenceWhenEntityOn` config value is
  **not** actually used by that node.

## 3. Shadow state

Each handler reads helper states from Node-RED's cached HA state, falling back to
a flow-context "shadow" copy it writes immediately before calling the service.
This papers over the window between issuing `input_select.select_option` and the
new state arriving back over the websocket.

## 4. Bugs, races and simplification opportunities

1. **`unavailable → off` counts as a completed cycle.** Washer/dryer "finish" fires
   when the sensor goes `off` and the helper says running, regardless of the
   previous state. A Zigbee drop-out or integration reload mid-cycle produces a
   false "dryer finished", a TTS announcement, and `Dry Done`.
2. **`unavailable → on` can double-count.** If the helper was changed (manually or by
   the race in #5) the washer start path increments the load counter again.
3. **Door reconnects clear laundry.** `unavailable → on` on a door sensor is treated as
   a door opening, clearing `Dry Done` and recording a "last done" time.
4. **Overdue uses `last_changed` of the helper.** `last_changed` resets on every HA
   restart, so overdue detection silently restarts after a reboot.
5. **Stale-state race.** Handlers read the HA state cache; the shadow is only used when
   the cache has *no* value, so a fast washer-off → dryer-on sequence can read a stale
   `Washing` and skip clearing `Wash Done`.
6. **Mark Done resets running appliances.** `LAUNDRY_MARK_DONE` shadows both appliances
   `Idle` and calls the external script even if one is mid-cycle; the next `off`
   then gets ignored or mis-handled.
7. **Hang Dry is unconditional.** It sets the washer `Idle` even if a new wash is
   running.
8. **Actions are not instance-scoped.** Any `LAUNDRY_*` action from any device or any
   other automation is handled.
9. **Dryer start doesn't clear the washer notification** although it clears
   `Wash Done`.
10. **First reminder timing is arbitrary.** The wall-clock 15-minute tick means the first
    reminder can arrive seconds after the "finished" notification.
11. **Reminder hour granularity.** Window can only be whole hours.
12. **Two HA server config nodes.** The On-Air check uses a different server node
    (`7ae7f6648a863d97`) from the rest of the flow.
13. **Dead events.** `washer_started`, `dryer_started` and
    `washer_finished_while_dryer_running` have no consumers.
14. **Load counter and state are separate helpers,** so they can drift (counter
    incremented, select failed, or vice versa).
15. **Dependency on an external template sensor** (`sensor.laundry_status`) and an
    external script (`script.laundry_mark_done`) whose behavior isn't captured.

## 5. Decisions taken in the integration

| Legacy behavior | Integration | Reason |
| --- | --- | --- |
| Finish on any `→ off` while running | Finish on trusted `on → off`; a reading that follows `unknown`/`unavailable` must stay stable for the *reconnect grace period* (default 120 s) before it is acted on | Fixes #1, #2, phantom cycles at startup |
| Door `→ on` from any state | Door must go `off → on` | Fixes #3 |
| Overdue from helper `last_changed` | Persisted completion timestamp | Fixes #4 |
| HA cache + shadow state | Single in-memory state machine, persisted to `.storage`, transitions run synchronously in the event loop | Fixes #5, #14 |
| Mark Done resets everything | Only clears appliances in a *done* state; running appliances are untouched | Fixes #6 |
| Hang Dry unconditional | Only clears washer if *Wash Done* | Fixes #7 |
| Global action IDs | Action IDs carry the config entry id | Fixes #8 |
| — | Dryer start clears the washer notification if it was showing the washer | Fixes #9 |
| Wall-clock reminder tick | Reminder due *interval* after completion, then every interval | Fixes #10 |
| Hour-only window | Time-of-day window (supports wrapping midnight) | Fixes #11 |
| `sensor.laundry_status` text | Built-in status sensor + built-in message text | Fixes #15 |
| `script.laundry_mark_done` | Built-in Mark Done (button, action, phone action) | Fixes #15 |
| No phone notification when washer finishes while dryer runs | Preserved; option *Notify when washer finishes while dryer is running* (default off) | Preserve intent |
| TTS only for dryer finished | Preserved | — |
| On-Air: announce only when `off` | Announce unless entity is `on`; `unknown`/`unavailable`/missing follows a configurable policy (default **suppress**, same as legacy) | Preserve intent |
| Notification titles, texts, tags, actions | Preserved (tags made instance-specific) | — |

## 6. Migration checklist

- [x] Washer start → Washing, load +1, `washer_started` event
- [x] Washer finish → Wash Done, `washer_finished` event (with `dryer_running`)
- [x] Washer finish notification + Hang Dry action (suppressed while dryer runs)
- [x] Dryer start → Drying, clears Wash Done, `dryer_started` event
- [x] Dryer finish → Dry Done, needs-attention on, `dryer_finished` event
- [x] Dryer finish notification + Mark as Done action
- [x] Dryer finish TTS with random message and all script parameters
- [x] On-Air suppression
- [x] Washer door after Wash Done → Idle, clear notification
- [x] Dryer door after Dry Done → Idle, alert off, last completed, clear notifications, `laundry_cleared`
- [x] Hang Dry action
- [x] Mark as Done action (replaces `script.laundry_mark_done`)
- [x] 15-minute reminders, 08:00–22:00, overdue after 60 min, high importance
- [x] Two notification tags (state, reminder)
- [x] Multiple phones
- [x] Load counter (with one-time import action)
- [x] Last completed timestamp (with one-time import action)
- [x] `dryer_alert` → `binary_sensor` *Needs attention* (attribute `dryer_waiting`)
- [x] Status text → *Status* sensor
