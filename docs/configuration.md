# Configuration reference

Everything is configured in the UI. No YAML is required.

## Initial setup

**Settings → Devices & services → Add integration → Laundry Controller**

### Step 1 – Sensors (required)

| Field | Description |
| --- | --- |
| Name | Device name and entity-ID prefix. Default `Laundry` → `sensor.laundry_status`, etc. |
| Washer running sensor | `binary_sensor` that is `on` while the washer runs. |
| Dryer running sensor | `binary_sensor` that is `on` while the dryer runs. |
| Washer door sensor | `binary_sensor` that is `on` when the washer door is open. |
| Dryer door sensor | `binary_sensor` that is `on` when the dryer door is open. |

All four must be different entities. A washer running sensor already used by
another Laundry Controller is rejected.

The running sensors should already be debounced (for example a power-based
template with `delay_off`). The integration acts on each `on → off` immediately,
just as the Node-RED flow did.

### Step 2 – Optional features

Phones to notify, announcement script, speaker device and On-Air entity. These
can be left empty and set later.

## Changing sensors

**Laundry Controller → ⋮ → Reconfigure.** The entry reloads; state and counts
are kept.

## Options (Configure)

### Phone notifications

| Option | Default | Description |
| --- | --- | --- |
| Phones to notify | none | Notify services, e.g. `mobile_app_pixel_bell`. The list shows existing `notify.*` services; you can also type one. Mobile-app services get action buttons, tags, importance and can be cleared. Other notify services get the title and message only. Empty = no notifications and no reminders. |
| NFC subscription tag | none | Choose an existing Home Assistant tag. If empty, **every selected phone always receives alerts** (legacy behavior). With a tag set, phone alerts are opt-in. |
| Subscription duration | 12 hours | Allowed range 1–168 hours; a repeat scan renews the full period. |
| Notify when the washer finishes while the dryer is running | off | The Node-RED flow sent nothing in this case. |

### Optional recipient routing

In **Configure → Phone notifications → Recipient routing scripts**, enter an
object mapping selected notify services to existing script entity IDs. Example:

```yaml
mobile_app_my_phone: script.my_notification_router
```

The script receives `title`, `message`, and `phone_data` (the original
notification tag, actions and importance). Only recipients eligible under
the existing NFC rules are routed. Missing or failing scripts fall back to
the original notify service. NFC scan confirmations and clear commands
always remain direct. Unmapped recipients are unchanged. Independent dryer
TTS remains configurable; disable it only if the routing script replaces
the same speaker delivery. Audio-only routing does not display phone action
buttons unless the script also sends the phone payload.

### NFC opt-in subscriptions

Choose the tag in **Configure → Phone notifications → NFC subscription tag**.
The tag must already be registered in Home Assistant (Settings → Tags).
The NFC setting is **optional**. With no tag selected, notifications continue
to reach every selected notify service regardless of scanning, including when
upgrading an older installation.

When a tag is selected, select *mobile_app* notify services only. A second
form, **Match phones to scanning devices**, appears after saving the notification
options. Map each selected notify service to the corresponding Home Assistant
Companion App device. This explicit mapping is configuration in your Home
Assistant instance, not hardcoded names or IDs in the integration's source.

When a mapped phone scans the selected tag using the Home Assistant Companion
App, it receives a confirmation and enables cycle-finished and reminder alerts
for the configured duration (default 12 hours). Repeated scans renew that
phone's expiration. Unmapped phones, unselected phones, and other tags do
nothing. Scanning from a device is not ownership of a laundry load; multiple
phones can be subscribed simultaneously. Notifications cease automatically
after expiration; TTS announcements are independent.

Subscription expiration times are saved alongside the integration's other
state and survive Home Assistant restarts. When a laundry notification is
cleared after completion, clear requests still go to *all* configured mobile-app
recipients, even expired ones, so stale notifications can be removed. Removing
the configured NFC tag returns immediately to the legacy notify-all mode.

**Migration from existing tag-scanned automations:** after configuring the
tag and device mappings in this integration, disable any prior NFC subscription
automation; the integration will now handle scans and confirmation messages.
Existing external input_datetime subscription helpers are not imported into
this integration. Each phone should scan the selected tag again once after
the change. Old helpers can be removed after verification.

### Smart-speaker announcements

| Option | Default | Description |
| --- | --- | --- |
| Announcement script | none | Script run when the dryer finishes. Empty = no announcements. |
| Speaker device | none | Device ID passed as `speaker_device`. Omitted when empty. |
| On-Air entity | none | Announcements are skipped while this entity is `on`. Evaluated at announcement time. |
| When the On-Air entity is unavailable | Stay silent | Also applies if the entity doesn't exist. *Stay silent* matches the Node-RED flow. |
| Messages | 10 legacy messages | One per line; one is chosen at random. |
| Language | `en-GB` | `language` |
| Voice | `RyanNeural` | `voice` |
| Volume | `0.7` | `volume` |
| LED color | `[0, 80, 255]` | `led_color` |
| LED brightness | `70` | `led_brightness` |
| Maximum light duration | `30` s | `max_light_duration` |

The script is called as `script.<name>` with these variables:

```yaml
speaker_device: 09aa5bd9cb63149e10f689141db50016   # if configured
message: "The dryer has completed its cycle. Clothes are ready."
language: en-GB
voice: RyanNeural
volume: 0.7
led_color: [0, 80, 255]
led_brightness: 70
max_light_duration: 30
```

Any script that accepts those fields (it may ignore the ones it doesn't need)
works. A minimal example without lights:

```yaml
script:
  laundry_announce:
    fields:
      message: {}
    sequence:
      - action: tts.speak
        target:
          entity_id: tts.home_assistant_cloud
        data:
          media_player_entity_id: media_player.kitchen
          message: "{{ message }}"
```

### Reminders

| Option | Default | Description |
| --- | --- | --- |
| Reminder interval | 15 min | First reminder one interval after a cycle finishes, then every interval. |
| Reminders allowed from | 08:00 | Start of the allowed window. |
| Reminders allowed until | 22:00 | End of the window (exclusive). May be earlier than the start to wrap past midnight. Same as start = all day. |
| Overdue after | 60 min | Reminders for laundry waiting longer than this are titled "OVERDUE: Laundry!" with high importance. |

Reminders can also be paused with the **Reminders** switch without changing
these settings.

### Advanced

| Option | Default | Description |
| --- | --- | --- |
| Reconnect grace period | 120 s | How long a running-sensor reading that follows `unknown`/`unavailable` (or Home Assistant start-up) must remain unchanged before the integration acts on it. See [architecture](architecture.md#sensor-trust-policy-reconnects-and-restarts). `0` acts immediately (not recommended). |

Saving any options page reloads the entry. State, counts and pending reminders
are preserved.
