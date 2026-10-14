# Migrating from the Node-RED flow

This is a controlled, reversible cut-over. The single most important rule:

> **Never run the Node-RED flow and the integration at the same time.** Both
> would count loads, send notifications and announce the dryer.

The integration does not touch, rename or delete any existing helper. It
creates its own entities next to them.

## What replaces what

| Node-RED / helper | Integration | Notes |
| --- | --- | --- |
| `input_select.washer_state` (`Idle`/`Washing`/`Wash Done`) | `sensor.laundry_washer_state` (`idle`/`washing`/`wash_done`) | Raw states are lower-case IDs; the UI shows "Idle", "Washing", "Wash done". Update automations that compare states. |
| `input_select.dryer_state` (`Idle`/`Drying`/`Dry Done`) | `sensor.laundry_dryer_state` (`idle`/`drying`/`dry_done`) | As above. |
| `input_boolean.dryer_alert` | `binary_sensor.laundry_needs_attention` | On while **either** appliance is done. For the exact old meaning use `is_state('sensor.laundry_dryer_state', 'dry_done')` or the `dryer_waiting` attribute. |
| `input_datetime.laundry_last_done` | `sensor.laundry_last_completed` | Timestamp sensor. Also set by Mark Done. |
| `counter.laundry_loads` | `sensor.laundry_loads` | Import once (below). |
| `sensor.laundry_status` (template) | `sensor.laundry_status` | Entity ID conflict, see step 3. |
| `script.laundry_mark_done` | `button.laundry_mark_done` / `laundry_controller.mark_done` | |
| Phone action `LAUNDRY_HANG_DRY` / `LAUNDRY_MARK_DONE` | `LAUNDRY_HANG_DRY:<entry_id>` / `LAUNDRY_MARK_DONE:<entry_id>` | Buttons on notifications sent *before* the cut-over stop working; dismiss them. |
| Tags `laundry_state` / `laundry_reminder` | `laundry_controller_<entry_id>_state` / `_reminder` | Old notifications are not cleared automatically. |
| `switch.on_air_sign_2_josh_on_air_led_power_2` (hard-coded) | On-Air entity option | |
| Flow config constants | Options pages | |

## Procedure

### 1. Install, don't configure yet

Install through HACS (see README) and restart Home Assistant. Do not add the
integration yet.

### 2. Pick a quiet moment

Cut over when both appliances are idle and nothing is waiting (washer and
dryer helpers `Idle`). The integration starts in Idle and cannot be put into a
"done" state manually.

Note the current values of `counter.laundry_loads` and
`input_datetime.laundry_last_done`.

### 3. Free the `sensor.laundry_status` entity ID (optional)

Your template sensor already uses `sensor.laundry_status`. If the integration
is added as-is, its status sensor becomes `sensor.laundry_status_2`.

To keep the name for the new sensor, first rename the old one:

* UI template helper: **Settings → Entities → Laundry status → ⚙ → Entity ID**
  → `sensor.laundry_status_legacy`.
* YAML template with a `unique_id`: rename it in the UI as above.
* YAML template without a `unique_id`: change its `name` in YAML (the entity ID
  follows the name) and reload template entities.

Nothing else collides: the other new entities live in the `sensor`,
`binary_sensor`, `switch` and `button` domains with new names.

### 4. Disable the Node-RED flow

In Node-RED, double-click the **Laundry Controller** tab → **Disabled** →
**Deploy**. Don't delete it; it's your rollback.

### 5. Add the integration

**Settings → Devices & services → Add integration → Laundry Controller**

| Field | Value |
| --- | --- |
| Name | `Laundry` |
| Washer running sensor | `binary_sensor.washer_activity_washer_running` |
| Dryer running sensor | `binary_sensor.dryer_activity_dryer_running` |
| Washer door sensor | `binary_sensor.washer_door` |
| Dryer door sensor | `binary_sensor.dryer_door` |
| Phones to notify | `mobile_app_pixel_bell`, `mobile_app_ashers_phone` |
| Announcement script | `script.smart_speaker_tts_with_light` |
| Speaker device | the device with ID `09aa5bd9cb63149e10f689141db50016` |
| On-Air entity | `switch.on_air_sign_2_josh_on_air_led_power_2` |

All other defaults (en-GB, RyanNeural, volume 0.7, blue LED at 70 %, 30 s,
the ten messages, reminders every 15 min from 08:00 to 22:00, overdue after
60 min) match the flow.

### 6. Import the load count and last-done time (one time)

Create and run this script once, then delete it:

```yaml
alias: Import legacy laundry state
sequence:
  - action: laundry_controller.set_load_count
    data:
      count: "{{ states('counter.laundry_loads') | int(0) }}"
  - if: "{{ has_value('input_datetime.laundry_last_done') }}"
    then:
      - action: laundry_controller.set_last_completed
        data:
          timestamp: "{{ states('input_datetime.laundry_last_done') }}"
```

The old `input_datetime` holds local time without a zone; it is interpreted in
Home Assistant's time zone.

### 7. Repoint dependants

* **`script.laundry_mark_done`**: anything else that calls it can keep doing so
  if you replace its sequence with:

  ```yaml
  sequence:
    - action: laundry_controller.mark_done
  ```

* **Automations / dashboards** reading the old helpers: switch them to the new
  entities (table above). Watch out for state comparisons (`Wash Done` →
  `wash_done`).
* If you'd rather keep old dashboards untouched for a while, mirror the new
  state into the old helpers with this automation. It writes helpers only — no
  notifications — so it is safe alongside the integration. Delete it once
  everything uses the new entities.

  ```yaml
  alias: Mirror Laundry Controller into legacy helpers
  mode: queued
  triggers:
    - trigger: state
      entity_id:
        - sensor.laundry_washer_state
        - sensor.laundry_dryer_state
        - sensor.laundry_loads
        - sensor.laundry_last_completed
  variables:
    names:
      idle: Idle
      washing: Washing
      wash_done: Wash Done
      drying: Drying
      dry_done: Dry Done
  actions:
    - action: input_select.select_option
      target:
        entity_id: input_select.washer_state
      data:
        option: "{{ names.get(states('sensor.laundry_washer_state'), 'Idle') }}"
    - action: input_select.select_option
      target:
        entity_id: input_select.dryer_state
      data:
        option: "{{ names.get(states('sensor.laundry_dryer_state'), 'Idle') }}"
    - action: >-
        input_boolean.turn_{{ 'on' if is_state('sensor.laundry_dryer_state',
        'dry_done') else 'off' }}
      target:
        entity_id: input_boolean.dryer_alert
    - action: counter.set_value
      target:
        entity_id: counter.laundry_loads
      data:
        value: "{{ states('sensor.laundry_loads') | int(0) }}"
    - if: "{{ has_value('sensor.laundry_last_completed') }}"
      then:
        - action: input_datetime.set_datetime
          target:
            entity_id: input_datetime.laundry_last_done
          data:
            timestamp: "{{ as_timestamp(states('sensor.laundry_last_completed')) }}"
  ```

### 8. Verify

1. Run the washer (or flip the running sensor in **Developer tools → States**):
   `sensor.laundry_loads` goes up by one; "Washer finished!" arrives on both
   phones with **Hang Dry (Done)**.
2. Tap **Hang Dry** → washer state goes to Idle and the notification clears.
3. Dryer cycle → "Dryer finished." with **Mark as Done**, speaker announcement
   (unless On-Air), *Needs attention* on.
4. Leave it: a "Laundry Reminder" arrives 15 minutes after the dryer finished
   and every 15 minutes after that; once the laundry has waited more than 60
   minutes they become "OVERDUE: Laundry!".
5. Open the dryer door → everything clears, *Last completed* updates.

The `laundry_controller_*` events can be watched in **Developer tools →
Events**.

### 9. Clean up (after a week or two)

Delete the Node-RED tab, the import script, the mirror automation (if used),
and the old helpers: `input_select.washer_state`, `input_select.dryer_state`,
`input_boolean.dryer_alert`, `input_datetime.laundry_last_done`,
`counter.laundry_loads`, the old status template and `script.laundry_mark_done`.
Their recorded history stays in the database until it ages out.

## Rollback

1. **Settings → Devices & services → Laundry Controller → ⋮ → Disable.**
2. Disable the mirror automation, if used.
3. Re-enable the Node-RED tab and deploy.

Re-enabling the integration later resumes from its saved state.
