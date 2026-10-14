"""Tests for the config, reconfigure and options flows."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.laundry_controller.const import (
    CONF_DRYER_DOOR,
    CONF_NOTIFY_WASHER_WHILE_DRYER_RUNNING,
    CONF_ON_AIR_ENTITY,
    CONF_OVERDUE_AFTER,
    CONF_RECIPIENTS,
    CONF_RECONNECT_GRACE,
    CONF_REMINDER_END,
    CONF_REMINDER_INTERVAL,
    CONF_REMINDER_START,
    CONF_TTS_SCRIPT,
    CONF_TTS_SPEAKER_DEVICE,
    DEFAULT_OPTIONS,
    DOMAIN,
)

from .conftest import (
    DRYER_DOOR,
    ON_AIR,
    PHONE,
    SCRIPT,
    SENSOR_DATA,
    WASHER_DOOR,
    make_entry,
    set_all_off,
    setup_entry,
)


async def test_user_flow(hass: HomeAssistant, notify_calls) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Laundry", **SENSOR_DATA}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "features"

    set_all_off(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_RECIPIENTS: [PHONE], CONF_TTS_SCRIPT: SCRIPT, CONF_ON_AIR_ENTITY: ON_AIR},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Laundry"
    assert result["data"] == SENSOR_DATA
    options = result["result"].options
    assert options[CONF_RECIPIENTS] == [PHONE]
    assert options[CONF_TTS_SCRIPT] == SCRIPT
    assert options[CONF_REMINDER_INTERVAL] == 15
    assert CONF_TTS_SPEAKER_DEVICE not in options


async def test_duplicate_entities_rejected(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Laundry", **SENSOR_DATA, CONF_DRYER_DOOR: WASHER_DOOR},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "duplicate_entities"}


async def test_already_configured(hass: HomeAssistant) -> None:
    make_entry().add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Laundry", **SENSOR_DATA}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(hass: HomeAssistant) -> None:
    set_all_off(hass)
    entry = make_entry()
    await setup_entry(hass, entry)
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    new = {**SENSOR_DATA, CONF_DRYER_DOOR: "binary_sensor.new_dryer_door"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_DRYER_DOOR] == "binary_sensor.new_dryer_door"
    assert entry.runtime_data._doors["binary_sensor.new_dryer_door"]
    assert DRYER_DOOR not in entry.runtime_data._doors


async def test_options_flow(hass: HomeAssistant, notify_calls) -> None:
    set_all_off(hass)
    entry = make_entry()
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "reminders"}
    )
    assert result["step_id"] == "reminders"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_REMINDER_INTERVAL: 30.0,
            CONF_REMINDER_START: "07:30:00",
            CONF_REMINDER_END: "21:00:00",
            CONF_OVERDUE_AFTER: 90.0,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_REMINDER_INTERVAL] == 30
    assert isinstance(entry.options[CONF_REMINDER_INTERVAL], int)
    assert entry.options[CONF_RECIPIENTS] == [PHONE]  # untouched

    # Clearing an optional entity removes it.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "announcements"}
    )
    announcement_input = {
        key: entry.options[key]
        for key in (
            "on_air_unavailable",
            "tts_messages",
            "tts_language",
            "tts_voice",
            "tts_volume",
            "tts_led_color",
            "tts_led_brightness",
            "tts_max_light_duration",
        )
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**announcement_input, CONF_TTS_SCRIPT: SCRIPT}
    )
    await hass.async_block_till_done()
    assert CONF_ON_AIR_ENTITY not in entry.options
    assert entry.options[CONF_TTS_SCRIPT] == SCRIPT

    for step, user_input in (
        (
            "notifications",
            {CONF_RECIPIENTS: [], CONF_NOTIFY_WASHER_WHILE_DRYER_RUNNING: True},
        ),
        ("advanced", {CONF_RECONNECT_GRACE: 60.0}),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": step}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input
        )
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_RECONNECT_GRACE] == 60
    assert entry.options[CONF_NOTIFY_WASHER_WHILE_DRYER_RUNNING] is True
    assert entry.runtime_data.notifier.recipients == []
    assert set(DEFAULT_OPTIONS) <= set(entry.options)
