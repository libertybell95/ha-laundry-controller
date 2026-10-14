"""Constants for the Laundry Controller integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "laundry_controller"

DEFAULT_NAME: Final = "Laundry"

# Config entry data (sensors; changed via reconfigure)
CONF_WASHER_RUNNING: Final = "washer_running"
CONF_DRYER_RUNNING: Final = "dryer_running"
CONF_WASHER_DOOR: Final = "washer_door"
CONF_DRYER_DOOR: Final = "dryer_door"
SENSOR_KEYS: Final = (
    CONF_WASHER_RUNNING,
    CONF_DRYER_RUNNING,
    CONF_WASHER_DOOR,
    CONF_DRYER_DOOR,
)

# Options: notifications
CONF_RECIPIENTS: Final = "recipients"
CONF_NOTIFY_WASHER_WHILE_DRYER_RUNNING: Final = "notify_washer_while_dryer_running"

# Options: announcements
CONF_TTS_SCRIPT: Final = "tts_script"
CONF_TTS_SPEAKER_DEVICE: Final = "tts_speaker_device"
CONF_TTS_MESSAGES: Final = "tts_messages"
CONF_TTS_LANGUAGE: Final = "tts_language"
CONF_TTS_VOICE: Final = "tts_voice"
CONF_TTS_VOLUME: Final = "tts_volume"
CONF_TTS_LED_COLOR: Final = "tts_led_color"
CONF_TTS_LED_BRIGHTNESS: Final = "tts_led_brightness"
CONF_TTS_MAX_LIGHT_DURATION: Final = "tts_max_light_duration"
CONF_ON_AIR_ENTITY: Final = "on_air_entity"
CONF_ON_AIR_UNAVAILABLE: Final = "on_air_unavailable"

ON_AIR_SUPPRESS: Final = "suppress"
ON_AIR_ANNOUNCE: Final = "announce"

# Options: reminders
CONF_REMINDER_INTERVAL: Final = "reminder_interval"
CONF_REMINDER_START: Final = "reminder_start"
CONF_REMINDER_END: Final = "reminder_end"
CONF_OVERDUE_AFTER: Final = "overdue_after"

# Options: advanced
CONF_RECONNECT_GRACE: Final = "reconnect_grace"

DEFAULT_TTS_MESSAGES: Final = (
    "Pardon the interruption. The dryer cycle has completed.",
    "Laundry update. The dryer is finished.",
    "The dryer has completed its cycle. Clothes are ready.",
    "Just a heads up. The dryer is done.",
    "Dryer cycle complete. Laundry is ready for retrieval.",
    "Attention please. The dryer has finished.",
    "Your laundry is dry and ready.",
    "The dryer has stopped. Time to collect the laundry.",
    "Laundry status update. Drying is complete.",
    "The dryer is no longer running. Clothes should be ready.",
)

DEFAULT_OPTIONS: Final[dict] = {
    CONF_RECIPIENTS: [],
    CONF_NOTIFY_WASHER_WHILE_DRYER_RUNNING: False,
    CONF_TTS_MESSAGES: "\n".join(DEFAULT_TTS_MESSAGES),
    CONF_TTS_LANGUAGE: "en-GB",
    CONF_TTS_VOICE: "RyanNeural",
    CONF_TTS_VOLUME: 0.7,
    CONF_TTS_LED_COLOR: [0, 80, 255],
    CONF_TTS_LED_BRIGHTNESS: 70,
    CONF_TTS_MAX_LIGHT_DURATION: 30,
    CONF_ON_AIR_UNAVAILABLE: ON_AIR_SUPPRESS,
    CONF_REMINDER_INTERVAL: 15,
    CONF_REMINDER_START: "08:00:00",
    CONF_REMINDER_END: "22:00:00",
    CONF_OVERDUE_AFTER: 60,
    CONF_RECONNECT_GRACE: 120,
}

# Phone notification action identifiers. The config entry id is appended
# ("LAUNDRY_MARK_DONE:<entry_id>") so actions are routed to one instance only.
ACTION_HANG_DRY: Final = "LAUNDRY_HANG_DRY"
ACTION_MARK_DONE: Final = "LAUNDRY_MARK_DONE"
MOBILE_APP_ACTION_EVENT: Final = "mobile_app_notification_action"

# Bus events fired by the integration (prefixed with the domain)
EVENT_WASHER_STARTED: Final = f"{DOMAIN}_washer_started"
EVENT_WASHER_FINISHED: Final = f"{DOMAIN}_washer_finished"
EVENT_DRYER_STARTED: Final = f"{DOMAIN}_dryer_started"
EVENT_DRYER_FINISHED: Final = f"{DOMAIN}_dryer_finished"
EVENT_LAUNDRY_CLEARED: Final = f"{DOMAIN}_laundry_cleared"

STORAGE_VERSION: Final = 1
SAVE_DELAY: Final = 1
