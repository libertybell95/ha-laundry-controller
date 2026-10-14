"""Smart-speaker announcements via a user-supplied script."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
import voluptuous as vol

from .const import (
    CONF_ON_AIR_ENTITY,
    CONF_ON_AIR_UNAVAILABLE,
    CONF_TTS_LANGUAGE,
    CONF_TTS_LED_BRIGHTNESS,
    CONF_TTS_LED_COLOR,
    CONF_TTS_MAX_LIGHT_DURATION,
    CONF_TTS_MESSAGES,
    CONF_TTS_SCRIPT,
    CONF_TTS_SPEAKER_DEVICE,
    CONF_TTS_VOICE,
    CONF_TTS_VOLUME,
    DEFAULT_TTS_MESSAGES,
    DOMAIN,
    ON_AIR_ANNOUNCE,
)

_LOGGER = logging.getLogger(__name__)

SCRIPT_DOMAIN = "script"
# Extra time allowed on top of the light duration for the script to finish.
SCRIPT_TIMEOUT_MARGIN = 120


def parse_messages(value: str | list[str] | None) -> list[str]:
    """Split the configured messages (one per line) into a list."""
    lines = value if isinstance(value, list) else (value or "").splitlines()
    messages = [line.strip() for line in lines if line.strip()]
    return messages or list(DEFAULT_TTS_MESSAGES)


class Announcer:
    """Run the announcement script for a finished dryer."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        entry_title: str,
        options: dict[str, Any],
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.entry_id = entry_id
        self.entry_title = entry_title
        self.options = options
        self.script: str | None = options.get(CONF_TTS_SCRIPT) or None
        self.messages = parse_messages(options.get(CONF_TTS_MESSAGES))
        self.last_result: str | None = None

    @property
    def configured(self) -> bool:
        """Return True if a script is configured."""
        return self.script is not None

    def suppression_reason(self) -> str | None:
        """Evaluate the On-Air entity now; return why to stay silent, if any."""
        entity_id = self.options.get(CONF_ON_AIR_ENTITY)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            if self.options.get(CONF_ON_AIR_UNAVAILABLE) == ON_AIR_ANNOUNCE:
                return None
            return f"{entity_id} is unavailable"
        if state.state == STATE_ON:
            return f"{entity_id} is on"
        return None

    def build_data(self, message: str) -> dict[str, Any]:
        """Build the script variables (legacy smart_speaker_tts_with_light API)."""
        data: dict[str, Any] = {
            "message": message,
            "language": self.options[CONF_TTS_LANGUAGE],
            "voice": self.options[CONF_TTS_VOICE],
            "volume": self.options[CONF_TTS_VOLUME],
            "led_color": list(self.options[CONF_TTS_LED_COLOR]),
            "led_brightness": self.options[CONF_TTS_LED_BRIGHTNESS],
            "max_light_duration": self.options[CONF_TTS_MAX_LIGHT_DURATION],
        }
        if speaker := self.options.get(CONF_TTS_SPEAKER_DEVICE):
            data["speaker_device"] = speaker
        return data

    async def async_announce(self) -> str:
        """Announce the dryer finishing. Never raises."""
        result = await self._async_announce()
        self.last_result = result
        return result

    async def _async_announce(self) -> str:
        if self.script is None:
            return "not configured"
        if reason := self.suppression_reason():
            _LOGGER.debug("Announcement suppressed: %s", reason)
            return f"suppressed: {reason}"
        issue_id = f"missing_tts_script_{self.entry_id}"
        object_id = self.script.removeprefix(f"{SCRIPT_DOMAIN}.")
        if not self.hass.services.has_service(SCRIPT_DOMAIN, object_id):
            _LOGGER.warning("Announcement script %s not found", self.script)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="missing_tts_script",
                translation_placeholders={
                    "script": self.script,
                    "name": self.entry_title,
                },
            )
            return f"failed: {self.script} not found"
        ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        data = self.build_data(random.choice(self.messages))
        timeout = (
            float(self.options[CONF_TTS_MAX_LIGHT_DURATION]) + SCRIPT_TIMEOUT_MARGIN
        )
        try:
            async with asyncio.timeout(timeout):
                await self.hass.services.async_call(
                    SCRIPT_DOMAIN, object_id, data, blocking=True
                )
        except (HomeAssistantError, TimeoutError, vol.Invalid) as err:
            _LOGGER.error("Announcement script %s failed: %s", self.script, err)
            return f"failed: {err}"
        except Exception as err:
            _LOGGER.exception("Unexpected error running %s", self.script)
            return f"failed: {err}"
        return "announced"
