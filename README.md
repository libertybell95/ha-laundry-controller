# Laundry Controller for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/libertybell95/ha-laundry-controller/actions/workflows/validate.yml/badge.svg)](https://github.com/libertybell95/ha-laundry-controller/actions/workflows/validate.yml)
[![Tests](https://github.com/libertybell95/ha-laundry-controller/actions/workflows/tests.yml/badge.svg)](https://github.com/libertybell95/ha-laundry-controller/actions/workflows/tests.yml)

Laundry Controller tracks your washer and dryer from four binary sensors,
counts loads, sends actionable phone notifications, nags you about laundry
left in the machine, and announces the finished dryer on a smart speaker —
natively inside Home Assistant, configured entirely in the UI.

It replaces a Node-RED flow with the same behavior, plus persistence across
restarts and protection against sensor drop-outs.

## Features

* Washer: **Idle → Washing → Wash done**; dryer: **Idle → Drying → Dry done**.
* Load counter, cycle durations, last-completed time.
* Phone notifications with **Hang Dry (Done)** and **Mark as Done** buttons,
  auto-cleared when the laundry is dealt with.
* Reminders every 15 minutes inside configurable hours; **OVERDUE** after 60 minutes.
* Smart-speaker announcement (via your own script) with random messages,
  muted while an "On-Air" entity is on.
* State and reminders survive restarts; sensor drop-outs don't create phantom
  cycles, duplicate loads or false "finished" alerts.
* Events and actions for your own automations.
* Multiple independent setups (e.g. two laundry rooms).

## Requirements

* Home Assistant 2025.3 or newer.
* Four `binary_sensor` entities:
  * washer running (`on` while running),
  * dryer running,
  * washer door (`on` = open),
  * dryer door.

  Running sensors are typically power- or vibration-based templates. They
  should be debounced (e.g. `delay_off`) so pauses mid-cycle don't read as
  "finished".
* Optional: the Home Assistant Companion app for actionable notifications, a
  script for announcements, an On-Air entity.

## Installation

### HACS (recommended)

1. **HACS → ⋮ → Custom repositories**, add
   `https://github.com/libertybell95/ha-laundry-controller` as type
   **Integration**.
2. Search for **Laundry Controller**, **Download**.
3. Restart Home Assistant.

### Manual

1. Download `laundry_controller.zip` from the
   [latest release](https://github.com/libertybell95/ha-laundry-controller/releases/latest).
2. Create `/config/custom_components/laundry_controller/` and extract the zip
   into it. The zip contains the integration's files directly, with no
   enclosing folder, so you end up with
   `/config/custom_components/laundry_controller/manifest.json`.
   - Alternatively, download the source archive and copy its
     `custom_components/laundry_controller/` folder into
     `/config/custom_components/`.
3. Restart Home Assistant.

### Updating

- **HACS**: an update appears when a new release is published. Install it and
  restart Home Assistant.
- **Manual**: replace `custom_components/laundry_controller/` and restart.

Saved state (appliance states, load count, pending reminders) is kept across
updates.

## Setup

**Settings → Devices & services → Add integration → Laundry Controller**

1. Choose a name (default *Laundry*) and the four sensors.
2. Optionally pick phones, an announcement script, a speaker device and an
   On-Air entity.

Everything else is under **Configure** (phone notifications, announcements,
reminders, advanced) and **Reconfigure** (sensors). See
[docs/configuration.md](docs/configuration.md) for every option.

**Migrating from Node-RED?** Follow [docs/migration.md](docs/migration.md) —
don't run both at once.

## Entities

Entity IDs below assume the default name *Laundry*.

| Entity | Description |
| --- | --- |
| `sensor.laundry_washer_state` | `idle`, `washing`, `wash_done`. Attributes `started_at`, `finished_at`. |
| `sensor.laundry_dryer_state` | `idle`, `drying`, `dry_done`. Attributes `started_at`, `finished_at`. |
| `sensor.laundry_status` | Combined: `idle`, `washing`, `drying`, `washing_and_drying`, `wash_done`, `dry_done`, `wash_and_dry_done`, `wash_done_drying`, `washing_dry_done`. |
| `sensor.laundry_loads` | Loads washed (counted when the washer starts). |
| `sensor.laundry_last_completed` | When laundry was last finished (dryer door opened, or Mark Done). |
| `sensor.laundry_washer_cycle_duration` | Duration of the last washer cycle (min). |
| `sensor.laundry_dryer_cycle_duration` | Duration of the last dryer cycle (min). |
| `sensor.laundry_next_reminder` | Diagnostic, disabled by default. |
| `binary_sensor.laundry_needs_attention` | On while finished laundry is waiting. Attributes `washer_waiting`, `dryer_waiting`, `washer_overdue`, `dryer_overdue` (overdue flags refresh at each reminder check). |
| `switch.laundry_reminders` | Pause/resume reminders. |
| `switch.laundry_announcements` | Pause/resume speaker announcements. |
| `button.laundry_mark_done` | Acknowledge all finished laundry. |

## How it behaves

| Happens | Result |
| --- | --- |
| Washer starts | Washing, load +1 |
| Washer finishes | Wash done; notification "Washer finished! Move clothes to the dryer." with **Hang Dry (Done)** — skipped if the dryer is running (configurable) |
| Washer door opened after finishing | Idle, washer notification cleared |
| Dryer starts | Drying; a finished washer goes to Idle (clothes moved) |
| Dryer finishes | Dry done; notification with **Mark as Done**; speaker announcement |
| Dryer door opened after finishing | Idle, notifications cleared, *last completed* updated |
| **Hang Dry** | Clears a finished washer (not a running one) |
| **Mark as Done** / button | Clears every finished appliance; running appliances are never touched |

Door openings while an appliance is running or idle are ignored.

### Notifications

Two categories, each with a stable tag so a new message replaces the old one:

* **Current state** – washer/dryer finished.
* **Reminders** – "Laundry Reminder" / "OVERDUE: Laundry!" (high importance),
  listing what is waiting and for how long.

Mobile-app notify services get buttons, tags and are cleared automatically.
Any other notify service gets plain title + message. Buttons only act on the
setup that sent them.

### Reminders

While laundry is waiting, the first reminder comes one interval (15 min) after
the cycle finished, then every interval. Outside the allowed hours
(08:00–22:00) reminders wait until the window opens. After a restart you get
at most one catch-up reminder, never a backlog.

### Announcements

When the dryer finishes, your script is called with `message`, `language`,
`voice`, `volume`, `led_color`, `led_brightness`, `max_light_duration` and
`speaker_device` — compatible with a `smart_speaker_tts_with_light`-style
script. Skipped while the On-Air entity is `on`; when it is unavailable the
default is to stay silent (configurable). A failing script never affects
laundry tracking.

### Sensor drop-outs and restarts

A running-sensor reading that follows `unavailable`/`unknown` (or a restart)
must stay unchanged for a grace period (120 s) before the integration acts on
it. So a sensor that drops out mid-cycle and comes back doesn't end the cycle
or count a new load, while a dryer that really finished during a restart is
still reported. Details: [docs/architecture.md](docs/architecture.md).

## Events

All events include `config_entry_id` and `name`.

| Event | Extra data |
| --- | --- |
| `laundry_controller_washer_started` | `loads` |
| `laundry_controller_washer_finished` | `duration` (s), `dryer_running` |
| `laundry_controller_dryer_started` | — |
| `laundry_controller_dryer_finished` | `duration` (s) |
| `laundry_controller_laundry_cleared` | `source` (`dryer_door`, `hang_dry`, `notification`, `button`, `action`), `appliances` |

## Actions

`config_entry_id` is optional when only one Laundry Controller is set up.

| Action | Fields | Description |
| --- | --- | --- |
| `laundry_controller.mark_done` | — | Acknowledge all finished laundry. |
| `laundry_controller.hang_dry` | — | Acknowledge a finished washer load. |
| `laundry_controller.reset` | — | Discard finished states and re-sync with the sensors (no loads counted, no notifications). |
| `laundry_controller.set_load_count` | `count` | Set the load counter. |
| `laundry_controller.set_last_completed` | `timestamp` | Set the last-completed time. |

## Automation examples

Flash a light when the dryer finishes:

```yaml
triggers:
  - trigger: event
    event_type: laundry_controller_dryer_finished
actions:
  - action: light.turn_on
    target:
      entity_id: light.hallway
    data:
      flash: long
```

Announce the washer too (the built-in announcement covers the dryer only):

```yaml
triggers:
  - trigger: event
    event_type: laundry_controller_washer_finished
    event_data:
      dryer_running: false
actions:
  - action: script.smart_speaker_tts_with_light
    data:
      message: The washer is done. Time to move the laundry.
```

Mark laundry done with an NFC tag on the dryer:

```yaml
triggers:
  - trigger: tag
    tag_id: laundry-room
actions:
  - action: laundry_controller.mark_done
```

Weekly load count notification:

```yaml
triggers:
  - trigger: time
    at: "20:00:00"
conditions:
  - condition: time
    weekday: sun
actions:
  - action: notify.mobile_app_pixel_bell
    data:
      message: "{{ states('sensor.laundry_loads') }} loads washed so far."
```

## Troubleshooting

* **Download diagnostics**: Laundry Controller → ⋮ → *Download diagnostics*
  shows current state, sensor trust, next reminder, last notification error
  and last announcement result (phone and speaker IDs are redacted).
* **Repairs**: a missing notify service or announcement script raises a
  repair issue; it clears itself once delivery works.
* **Cycle didn't finish after a sensor dropped out**: it will finish once the
  sensor has reported `off` for the grace period (Configure → Advanced).
* **Washer "finished" in the middle of a cycle**: debounce the running sensor
  (`delay_off`).
* **No notification when the washer finished**: by default there is none while
  the dryer is running (as in the Node-RED flow). Enable it under Configure →
  Phone notifications.
* **Old notification buttons do nothing**: notifications sent by Node-RED or
  another setup are deliberately ignored.
* **Debug logging**:

  ```yaml
  logger:
    logs:
      custom_components.laundry_controller: debug
  ```

## Known limitations

* Notification texts are English (entity names and states are translatable).
* Only the dryer finishing is announced; use the events for anything else.
* An appliance can't be put into a "done" state by hand, so a finished load
  discarded by *Reset* (or missed while the integration was disabled) can't be
  restored.
* The overdue attributes on *Needs attention* refresh at each reminder check,
  not continuously.
* Cycle detection is only as good as the running sensors; the integration
  doesn't debounce `on → off` itself.

## Development

```sh
uv venv -p 3.14 && uv pip install pytest-homeassistant-custom-component ruff
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

### Release process (maintainers)

1. Bump `version` in `custom_components/laundry_controller/manifest.json` and
   `pyproject.toml`.
2. Commit, then tag `vX.Y.Z` (for example `v0.1.0`) and publish a GitHub
   release from that tag.
3. The `Release` workflow checks that the tag matches the manifest version and
   attaches `laundry_controller.zip`. HACS uses the GitHub release list.

The reference Node-RED export is in
[references/node-red-flow.json](references/node-red-flow.json) and its
behavior is documented in [docs/legacy-behavior.md](docs/legacy-behavior.md).

## License

MIT
