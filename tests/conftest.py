"""Shared fixtures for Laundry Controller tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.laundry_controller.const import (
    CONF_DRYER_DOOR,
    CONF_DRYER_RUNNING,
    CONF_ON_AIR_ENTITY,
    CONF_RECIPIENTS,
    CONF_RECONNECT_GRACE,
    CONF_TTS_SCRIPT,
    CONF_TTS_SPEAKER_DEVICE,
    CONF_WASHER_DOOR,
    CONF_WASHER_RUNNING,
    DEFAULT_OPTIONS,
    DOMAIN,
)

WASHER = "binary_sensor.washer_activity_washer_running"
DRYER = "binary_sensor.dryer_activity_dryer_running"
WASHER_DOOR = "binary_sensor.washer_door"
DRYER_DOOR = "binary_sensor.dryer_door"
ON_AIR = "switch.on_air"
PHONE = "mobile_app_pixel_bell"
SCRIPT = "script.smart_speaker_tts_with_light"
SPEAKER = "09aa5bd9cb63149e10f689141db50016"

SENSOR_DATA = {
    CONF_WASHER_RUNNING: WASHER,
    CONF_DRYER_RUNNING: DRYER,
    CONF_WASHER_DOOR: WASHER_DOOR,
    CONF_DRYER_DOOR: DRYER_DOOR,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None]:
    """Enable custom integrations in all tests."""
    yield


@pytest.fixture
def notify_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Mock the phone notify service."""
    return async_mock_service(hass, "notify", PHONE)


@pytest.fixture
def script_calls(hass: HomeAssistant) -> list[ServiceCall]:
    """Mock the announcement script."""
    return async_mock_service(hass, "script", "smart_speaker_tts_with_light")


def make_entry(
    *,
    data: dict[str, Any] | None = None,
    title: str = "Laundry",
    **options: Any,
) -> MockConfigEntry:
    """Create a config entry with test defaults (no reconnect grace)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data=data or SENSOR_DATA,
        options={
            **DEFAULT_OPTIONS,
            CONF_RECIPIENTS: [PHONE],
            CONF_TTS_SCRIPT: SCRIPT,
            CONF_TTS_SPEAKER_DEVICE: SPEAKER,
            CONF_ON_AIR_ENTITY: ON_AIR,
            CONF_RECONNECT_GRACE: 0,
            **options,
        },
    )


def set_all_off(hass: HomeAssistant, data: dict[str, str] | None = None) -> None:
    """Put all source sensors in the closed/off state."""
    for entity_id in (data or SENSOR_DATA).values():
        hass.states.async_set(entity_id, "off")
    hass.states.async_set(ON_AIR, "off")


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up an entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle(hass)


async def settle(hass: HomeAssistant) -> None:
    """Wait for state changes and background notification tasks."""
    await hass.async_block_till_done(wait_background_tasks=True)
