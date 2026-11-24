# Changelog

## 0.2.0 – Optional NFC notification subscriptions

- Add optional NFC tag selection in the integration's Phone notifications options.
- When no NFC tag is configured, continue notifying all selected phones.
- Add configurable 1–168-hour subscription duration (default 12 hours).
- Match selected mobile-app notification services to scanning devices in the UI.
- Subscribe and renew per-device subscriptions on Home Assistant NFC scans.
- Send confirmation notifications and persist expirations across restarts.
- Filter finished-cycle and reminder notifications at the point of delivery.
- Continue clearing old notifications for configured phones after subscriptions expire.
- Document upgrade and migration from external NFC automations and helpers.

## 0.1.1

- Existing Laundry Controller integration behavior.
