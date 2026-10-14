"""Integration tests for Laundry Controller running inside Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.laundry_controller.const import (
    CONF_ON_AIR_UNAVAILABLE,
    CONF_RECIPIENTS,
    CONF_RECONNECT_GRACE,
    CONF_TTS_SCRIPT,
    DOMAIN,
    ON_AIR_ANNOUNCE,
)
from custom_components.laundry_controller.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import (
    DRYER,
    DRYER_DOOR,
    ON_AIR,
    PHONE,
    SPEAKER,
    WASHER,
    WASHER_DOOR,
    make_entry,
    set_all_off,
    settle,
    setup_entry,
)

NOON = "2026-10-14 12:00:00-07:00"  # tests run in US/Pacific


def state(hass: HomeAssistant, entity_id: str) -> str:
    st = hass.states.get(entity_id)
    assert st is not None, entity_id
    return st.state


async def flip(hass: HomeAssistant, entity_id: str, value: str) -> None:
    hass.states.async_set(entity_id, value)
    await settle(hass)


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, **delta) -> None:
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass, dt_util.utcnow())
    await settle(hass)


def sent(calls: list[ServiceCall]) -> list[dict]:
    return [c.data for c in calls if c.data["message"] != "clear_notification"]


def cleared(calls: list[ServiceCall]) -> list[str]:
    return [
        c.data["data"]["tag"]
        for c in calls
        if c.data["message"] == "clear_notification"
    ]


@pytest.fixture
async def entry(hass: HomeAssistant, notify_calls, script_calls, freezer):
    freezer.move_to(NOON)
    set_all_off(hass)
    config_entry = make_entry()
    await setup_entry(hass, config_entry)
    return config_entry


async def test_entities_created(hass: HomeAssistant, entry) -> None:
    assert state(hass, "sensor.laundry_washer_state") == "idle"
    assert state(hass, "sensor.laundry_dryer_state") == "idle"
    assert state(hass, "sensor.laundry_status") == "idle"
    assert state(hass, "sensor.laundry_loads") == "0"
    assert state(hass, "sensor.laundry_last_completed") == "unknown"
    assert state(hass, "binary_sensor.laundry_needs_attention") == "off"
    assert state(hass, "switch.laundry_reminders") == "on"
    assert state(hass, "switch.laundry_announcements") == "on"
    assert hass.states.get("button.laundry_mark_done") is not None
    assert hass.states.get("sensor.laundry_washer_cycle_duration") is not None
    # Diagnostic sensor disabled by default
    assert hass.states.get("sensor.laundry_next_reminder") is None


async def test_full_laundry_cycle(
    hass: HomeAssistant, entry, notify_calls, script_calls, freezer
) -> None:
    started = async_capture_events(hass, f"{DOMAIN}_washer_started")
    finished = async_capture_events(hass, f"{DOMAIN}_washer_finished")
    dryer_finished = async_capture_events(hass, f"{DOMAIN}_dryer_finished")
    cleared_events = async_capture_events(hass, f"{DOMAIN}_laundry_cleared")

    await flip(hass, WASHER, "on")
    assert state(hass, "sensor.laundry_washer_state") == "washing"
    assert state(hass, "sensor.laundry_loads") == "1"
    assert started[0].data["config_entry_id"] == entry.entry_id
    assert started[0].data["loads"] == 1

    freezer.tick(timedelta(minutes=45))
    await flip(hass, WASHER, "off")
    assert state(hass, "sensor.laundry_washer_state") == "wash_done"
    assert state(hass, "sensor.laundry_washer_cycle_duration") == "45.0"
    assert finished[0].data["dryer_running"] is False
    msg = sent(notify_calls)[-1]
    assert msg["message"] == "Washer finished! Move clothes to the dryer."
    assert msg["data"]["actions"] == [
        {"action": f"LAUNDRY_HANG_DRY:{entry.entry_id}", "title": "Hang Dry (Done)"}
    ]
    state_tag = msg["data"]["tag"]

    await flip(hass, DRYER, "on")
    assert state(hass, "sensor.laundry_washer_state") == "idle"
    assert state(hass, "sensor.laundry_dryer_state") == "drying"
    assert state_tag in cleared(notify_calls)

    freezer.tick(timedelta(minutes=60))
    await flip(hass, DRYER, "off")
    assert state(hass, "sensor.laundry_dryer_state") == "dry_done"
    assert state(hass, "binary_sensor.laundry_needs_attention") == "on"
    assert len(dryer_finished) == 1
    msg = sent(notify_calls)[-1]
    assert msg["message"] == "Dryer finished. Laundry is ready."
    assert msg["data"]["actions"][0]["title"] == "Mark as Done"
    assert len(script_calls) == 1
    data = script_calls[0].data
    assert data["speaker_device"] == SPEAKER
    assert data["language"] == "en-GB"
    assert data["voice"] == "RyanNeural"
    assert data["volume"] == 0.7
    assert data["led_color"] == [0, 80, 255]
    assert data["led_brightness"] == 70
    assert data["max_light_duration"] == 30
    assert data["message"]

    notify_calls.clear()
    await flip(hass, DRYER_DOOR, "on")
    assert state(hass, "sensor.laundry_dryer_state") == "idle"
    assert state(hass, "binary_sensor.laundry_needs_attention") == "off"
    assert state(hass, "sensor.laundry_last_completed") != "unknown"
    assert cleared_events[0].data["source"] == "dryer_door"
    assert len(cleared(notify_calls)) == 2  # state + reminder


async def test_washer_door_after_done(hass: HomeAssistant, entry, notify_calls) -> None:
    await flip(hass, WASHER, "on")
    await flip(hass, WASHER, "off")
    notify_calls.clear()
    await flip(hass, WASHER_DOOR, "on")
    assert state(hass, "sensor.laundry_washer_state") == "idle"
    assert any(tag.endswith("_state") for tag in cleared(notify_calls))


async def test_door_reconnecting_open_is_ignored(hass: HomeAssistant, entry) -> None:
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    await flip(hass, DRYER_DOOR, "unavailable")
    await flip(hass, DRYER_DOOR, "on")
    assert state(hass, "sensor.laundry_dryer_state") == "dry_done"


async def test_hang_dry_action(hass: HomeAssistant, entry, notify_calls) -> None:
    await flip(hass, WASHER, "on")
    await flip(hass, WASHER, "off")
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": f"LAUNDRY_HANG_DRY:{entry.entry_id}"},
    )
    await settle(hass)
    assert state(hass, "sensor.laundry_washer_state") == "idle"


async def test_mark_done_action_and_isolation(
    hass: HomeAssistant, entry, notify_calls
) -> None:
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    # Legacy (un-scoped) and foreign actions are ignored.
    for action in ("LAUNDRY_MARK_DONE", "LAUNDRY_MARK_DONE:someone_else", None):
        hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await settle(hass)
    assert state(hass, "sensor.laundry_dryer_state") == "dry_done"

    notify_calls.clear()
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": f"LAUNDRY_MARK_DONE:{entry.entry_id}"},
    )
    await settle(hass)
    assert state(hass, "sensor.laundry_dryer_state") == "idle"
    assert len(cleared(notify_calls)) == 2


async def test_mark_done_button_keeps_running_washer(
    hass: HomeAssistant, entry
) -> None:
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    await flip(hass, WASHER, "on")
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.laundry_mark_done"}, blocking=True
    )
    await settle(hass)
    assert state(hass, "sensor.laundry_dryer_state") == "idle"
    assert state(hass, "sensor.laundry_washer_state") == "washing"


async def test_repeated_events_count_once(hass: HomeAssistant, entry) -> None:
    await flip(hass, WASHER, "on")
    hass.states.async_set(WASHER, "on", {"changed": "attribute only"})
    await settle(hass)
    assert state(hass, "sensor.laundry_loads") == "1"


async def test_unavailable_sensor_policy(
    hass: HomeAssistant, notify_calls, script_calls, freezer
) -> None:
    freezer.move_to(NOON)
    set_all_off(hass)
    config_entry = make_entry(**{CONF_RECONNECT_GRACE: 120})
    await setup_entry(hass, config_entry)
    await tick(hass, freezer, seconds=121)  # trust the initial readings

    await flip(hass, DRYER, "on")
    assert state(hass, "sensor.laundry_dryer_state") == "drying"
    await flip(hass, DRYER, "unavailable")
    await flip(hass, DRYER, "off")
    # No completion yet: the reading follows "unavailable".
    assert state(hass, "sensor.laundry_dryer_state") == "drying"
    await tick(hass, freezer, seconds=60)
    await flip(hass, DRYER, "on")  # it was still running
    await tick(hass, freezer, seconds=200)
    assert state(hass, "sensor.laundry_dryer_state") == "drying"
    assert script_calls == []

    # Disconnect, reconnect off and stay off: completes after the grace.
    await flip(hass, DRYER, "unavailable")
    await flip(hass, DRYER, "off")
    await tick(hass, freezer, seconds=121)
    assert state(hass, "sensor.laundry_dryer_state") == "dry_done"
    assert len(script_calls) == 1

    # Reconnect without a cycle does nothing.
    await flip(hass, WASHER, "unavailable")
    await flip(hass, WASHER, "off")
    await tick(hass, freezer, seconds=121)
    assert state(hass, "sensor.laundry_washer_state") == "idle"
    assert state(hass, "sensor.laundry_loads") == "0"


async def test_restart_during_active_cycle(
    hass: HomeAssistant, notify_calls, script_calls, freezer
) -> None:
    freezer.move_to(NOON)
    set_all_off(hass)
    config_entry = make_entry(**{CONF_RECONNECT_GRACE: 120})
    await setup_entry(hass, config_entry)
    await tick(hass, freezer, seconds=121)
    await flip(hass, WASHER, "on")
    assert state(hass, "sensor.laundry_loads") == "1"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await settle(hass)
    # Sensor flaps while Home Assistant is "down".
    hass.states.async_set(WASHER, "unavailable")
    await tick(hass, freezer, minutes=5)
    hass.states.async_set(WASHER, "on")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await settle(hass)

    assert state(hass, "sensor.laundry_washer_state") == "washing"
    await tick(hass, freezer, seconds=121)
    assert state(hass, "sensor.laundry_loads") == "1"  # no duplicate

    await tick(hass, freezer, minutes=30)
    await flip(hass, WASHER, "off")
    assert state(hass, "sensor.laundry_washer_state") == "wash_done"
    assert float(state(hass, "sensor.laundry_washer_cycle_duration")) == pytest.approx(
        37, abs=0.1
    )


async def test_restart_with_pending_laundry_and_reminders(
    hass: HomeAssistant, notify_calls, script_calls, freezer
) -> None:
    freezer.move_to(NOON)
    set_all_off(hass)
    config_entry = make_entry()
    await setup_entry(hass, config_entry)
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await settle(hass)

    # Down for 3 hours: on return exactly one (overdue) reminder, no backlog.
    freezer.tick(timedelta(hours=3))
    notify_calls.clear()
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await settle(hass)
    await tick(hass, freezer, seconds=1)
    assert state(hass, "sensor.laundry_dryer_state") == "dry_done"
    reminders = sent(notify_calls)
    assert len(reminders) == 1
    assert reminders[0]["title"] == "OVERDUE: Laundry!"
    assert reminders[0]["data"]["importance"] == "high"
    assert reminders[0]["message"] == "Dryer finished 3 h ago."

    await tick(hass, freezer, minutes=14)
    assert len(sent(notify_calls)) == 1
    await tick(hass, freezer, minutes=1)
    assert len(sent(notify_calls)) == 2


async def test_reminders_timing_quiet_hours_and_switch(
    hass: HomeAssistant, notify_calls, script_calls, freezer
) -> None:
    freezer.move_to("2026-10-14 21:40:00-07:00")
    set_all_off(hass)
    await setup_entry(hass, make_entry())
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    notify_calls.clear()

    await tick(hass, freezer, minutes=15)  # 21:55 -> first reminder
    assert [m["title"] for m in sent(notify_calls)] == ["Laundry Reminder"]
    await tick(hass, freezer, minutes=15)  # 22:10 -> quiet
    await tick(hass, freezer, hours=9)  # 07:10 -> quiet
    assert len(sent(notify_calls)) == 1
    await tick(hass, freezer, minutes=50)  # 08:00 -> window opens
    assert len(sent(notify_calls)) == 2
    assert sent(notify_calls)[-1]["title"] == "OVERDUE: Laundry!"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.laundry_reminders"}, blocking=True
    )
    await tick(hass, freezer, minutes=30)
    assert len(sent(notify_calls)) == 2
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.laundry_reminders"}, blocking=True
    )
    await tick(hass, freezer, seconds=1)
    assert len(sent(notify_calls)) == 3

    # Acknowledging stops reminders.
    await flip(hass, DRYER_DOOR, "on")
    await tick(hass, freezer, hours=1)
    assert len(sent(notify_calls)) == 3


async def test_tts_on_air_suppression(hass: HomeAssistant, entry, script_calls) -> None:
    hass.states.async_set(ON_AIR, "on")
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    assert script_calls == []
    assert entry.runtime_data.announcer.last_result == f"suppressed: {ON_AIR} is on"

    hass.states.async_set(ON_AIR, "unavailable")
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    assert script_calls == []

    hass.states.async_set(ON_AIR, "off")
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    assert len(script_calls) == 1


async def test_tts_on_air_unavailable_announce_policy(
    hass: HomeAssistant, notify_calls, script_calls, freezer
) -> None:
    set_all_off(hass)
    await setup_entry(hass, make_entry(**{CONF_ON_AIR_UNAVAILABLE: ON_AIR_ANNOUNCE}))
    hass.states.async_remove(ON_AIR)
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    assert len(script_calls) == 1


async def test_tts_switch_off(hass: HomeAssistant, entry, script_calls) -> None:
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.laundry_announcements"},
        blocking=True,
    )
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    assert script_calls == []
    assert state(hass, "sensor.laundry_dryer_state") == "dry_done"


async def test_missing_services_do_not_break_state(
    hass: HomeAssistant, freezer
) -> None:
    """No notify service and no script registered at all."""
    set_all_off(hass)
    config_entry = make_entry(**{CONF_RECIPIENTS: ["mobile_app_gone"]})
    await setup_entry(hass, config_entry)
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    assert state(hass, "sensor.laundry_dryer_state") == "dry_done"
    issues = ir.async_get(hass)
    assert issues.async_get_issue(
        DOMAIN, f"missing_notify_{config_entry.entry_id}_mobile_app_gone"
    )
    assert issues.async_get_issue(DOMAIN, f"missing_tts_script_{config_entry.entry_id}")
    assert config_entry.runtime_data.announcer.last_result.startswith("failed")


async def test_failing_services_do_not_break_state(
    hass: HomeAssistant, freezer
) -> None:
    async def boom(call: ServiceCall) -> None:
        raise HomeAssistantError("push failed")

    hass.services.async_register("notify", PHONE, boom)
    hass.services.async_register("script", "smart_speaker_tts_with_light", boom)
    set_all_off(hass)
    config_entry = make_entry()
    await setup_entry(hass, config_entry)
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    await flip(hass, DRYER_DOOR, "on")
    assert state(hass, "sensor.laundry_dryer_state") == "idle"
    controller = config_entry.runtime_data
    assert "push failed" in controller.notifier.last_error
    assert "push failed" in controller.announcer.last_result


async def test_no_tts_script_configured(
    hass: HomeAssistant, notify_calls, freezer
) -> None:
    set_all_off(hass)
    config_entry = make_entry(**{CONF_TTS_SCRIPT: None})
    await setup_entry(hass, config_entry)
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    assert config_entry.runtime_data.announcer.last_result == "not configured"


async def test_services(hass: HomeAssistant, entry) -> None:
    await hass.services.async_call(
        DOMAIN, "set_load_count", {"count": 412}, blocking=True
    )
    assert state(hass, "sensor.laundry_loads") == "412"
    await hass.services.async_call(
        DOMAIN,
        "set_last_completed",
        {"timestamp": "2026-10-01 18:30:00"},
        blocking=True,
    )
    assert state(hass, "sensor.laundry_last_completed").startswith(
        "2026-10-02T01:30:00"
    )

    await flip(hass, WASHER, "on")
    await flip(hass, WASHER, "off")
    await hass.services.async_call(DOMAIN, "hang_dry", {}, blocking=True)
    assert state(hass, "sensor.laundry_washer_state") == "idle"

    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    await flip(hass, WASHER, "on")
    await hass.services.async_call(DOMAIN, "reset", {}, blocking=True)
    assert state(hass, "sensor.laundry_dryer_state") == "idle"
    assert state(hass, "sensor.laundry_washer_state") == "washing"
    assert state(hass, "sensor.laundry_loads") == "414"  # two washer starts

    await hass.services.async_call(
        DOMAIN, "mark_done", {"config_entry_id": entry.entry_id}, blocking=True
    )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "mark_done", {"config_entry_id": "nope"}, blocking=True
        )


async def test_multiple_instances(
    hass: HomeAssistant, notify_calls, script_calls, freezer
) -> None:
    set_all_off(hass)
    first = make_entry()
    await setup_entry(hass, first)
    other_sensors = {
        "washer_running": "binary_sensor.w2",
        "dryer_running": "binary_sensor.d2",
        "washer_door": "binary_sensor.wd2",
        "dryer_door": "binary_sensor.dd2",
    }
    set_all_off(hass, other_sensors)
    second = make_entry(data=other_sensors, title="Basement")
    await setup_entry(hass, second)

    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    await flip(hass, "binary_sensor.d2", "on")
    await flip(hass, "binary_sensor.d2", "off")
    assert state(hass, "sensor.basement_dryer_state") == "dry_done"
    tags = {m["data"]["tag"] for m in sent(notify_calls)}
    assert len(tags) == 2  # instance-specific tags

    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": f"LAUNDRY_MARK_DONE:{second.entry_id}"},
    )
    await settle(hass)
    assert state(hass, "sensor.basement_dryer_state") == "idle"
    assert state(hass, "sensor.laundry_dryer_state") == "dry_done"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "mark_done", {}, blocking=True)


async def test_unload_cleans_up(
    hass: HomeAssistant, entry, notify_calls, script_calls
) -> None:
    controller = entry.runtime_data
    await flip(hass, DRYER, "on")
    await flip(hass, DRYER, "off")
    assert controller.next_reminder is not None
    events = async_capture_events(hass, f"{DOMAIN}_dryer_started")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await settle(hass)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert controller._unsubs == []
    assert controller._reminder_unsub is None
    assert controller._listeners == []

    notify_calls.clear()
    await flip(hass, DRYER, "on")
    hass.bus.async_fire(
        "mobile_app_notification_action",
        {"action": f"LAUNDRY_MARK_DONE:{entry.entry_id}"},
    )
    await settle(hass)
    assert events == []
    assert notify_calls == []

    assert await hass.config_entries.async_remove(entry.entry_id)
    await settle(hass)


async def test_reload_on_options_change(hass: HomeAssistant, entry) -> None:
    old = entry.runtime_data
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_RECIPIENTS: []}
    )
    await settle(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old
    assert entry.runtime_data.notifier.recipients == []


async def test_diagnostics(hass: HomeAssistant, entry) -> None:
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["options"][CONF_RECIPIENTS] == "**REDACTED**"
    assert diag["state"]["machine"]["washer"]["phase"] == "idle"


async def test_reload_keeps_trust_in_stable_readings(
    hass: HomeAssistant, notify_calls, script_calls, freezer
) -> None:
    """An options reload is not a sensor interruption."""
    freezer.move_to(NOON)
    set_all_off(hass)
    config_entry = make_entry(**{CONF_RECONNECT_GRACE: 120})
    await setup_entry(hass, config_entry)
    await tick(hass, freezer, seconds=121)
    await flip(hass, DRYER, "on")
    await tick(hass, freezer, minutes=10)

    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, CONF_RECIPIENTS: [PHONE]}
    )
    hass.config_entries.async_update_entry(
        config_entry, options={**config_entry.options, "tts_volume": 0.5}
    )
    await settle(hass)
    await flip(hass, DRYER, "off")
    assert state(hass, "sensor.laundry_dryer_state") == "dry_done"
    assert script_calls[0].data["volume"] == 0.5
