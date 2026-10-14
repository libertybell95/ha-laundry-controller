"""Diagnostics for Laundry Controller."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_RECIPIENTS, CONF_TTS_SPEAKER_DEVICE
from .coordinator import LaundryConfigEntry

TO_REDACT = {CONF_RECIPIENTS, CONF_TTS_SPEAKER_DEVICE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LaundryConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    controller = entry.runtime_data
    machine = controller.machine
    return {
        "data": dict(entry.data),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "recipient_count": len(controller.notifier.recipients),
        "state": controller._data(),  # noqa: SLF001
        "sensor_readings": {
            appliance.value: {
                "reading": record.reading,
                "trusted": record.trusted,
                "reading_since": (
                    record.reading_since.isoformat() if record.reading_since else None
                ),
            }
            for appliance, record in machine.records.items()
        },
        "next_confirm_at": (
            confirm.isoformat() if (confirm := machine.next_confirm_at()) else None
        ),
        "next_reminder": (
            controller.next_reminder.isoformat() if controller.next_reminder else None
        ),
        "last_notification_error": controller.notifier.last_error,
        "last_announcement": controller.announcer.last_result,
    }
