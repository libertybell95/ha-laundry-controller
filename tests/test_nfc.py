"""Optional NFC opt-in subscription integration tests."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.laundry_controller.const import (
    CONF_NFC_DEVICES,
    CONF_NFC_DURATION,
    CONF_NFC_TAG,
)

from .conftest import PHONE, WASHER, make_entry, set_all_off, settle, setup_entry

TAG_ENTITY = "tag.test_washer"
TAG_ID = "example-nfc-tag"
DEVICE_ID = "example-companion-device"


async def test_no_tag_keeps_legacy_notify_all(
    hass: HomeAssistant, notify_calls
) -> None:
    """An unset tag must never change recipients or require scanning."""
    set_all_off(hass)
    entry = make_entry()
    await setup_entry(hass, entry)
    await _washer_finishes(hass)
    assert any(
        c.data.get("message", "").startswith("Washer finished") for c in notify_calls
    )


async def test_tag_requires_scan_and_expires(
    hass: HomeAssistant, notify_calls, freezer
) -> None:
    """Only mapped phones with a live subscription receive laundry alerts."""
    set_all_off(hass)
    hass.states.async_set(TAG_ENTITY, "unknown", {"tag_id": TAG_ID})
    entry = make_entry(
        **{
            CONF_NFC_TAG: TAG_ENTITY,
            CONF_NFC_DURATION: 12,
            CONF_NFC_DEVICES: {PHONE: DEVICE_ID},
        }
    )
    await setup_entry(hass, entry)
    notifier = entry.runtime_data.notifier
    assert notifier.eligible_recipients() == []

    # A different tag or unregistered device does not grant access.
    hass.bus.async_fire("tag_scanned", {"tag_id": "different", "device_id": DEVICE_ID})
    hass.bus.async_fire("tag_scanned", {"tag_id": TAG_ID, "device_id": "unknown"})
    await settle(hass)
    assert notifier.eligible_recipients() == []
    assert not notify_calls

    hass.bus.async_fire("tag_scanned", {"tag_id": TAG_ID, "device_id": DEVICE_ID})
    await settle(hass)
    assert notifier.eligible_recipients() == [PHONE]
    assert any(c.data.get("title") == "Laundry alerts enabled" for c in notify_calls)
    first = notifier.subscriptions[DEVICE_ID]

    freezer.tick(timedelta(hours=1))
    hass.bus.async_fire("tag_scanned", {"tag_id": TAG_ID, "device_id": DEVICE_ID})
    await settle(hass)
    assert notifier.subscriptions[DEVICE_ID] > first

    freezer.tick(timedelta(hours=12, seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await settle(hass)
    assert notifier.eligible_recipients() == []
    before = len(notify_calls)
    await _washer_finishes(hass)
    assert not any(
        c.data.get("message", "").startswith("Washer finished")
        for c in notify_calls[before:]
    )


async def test_subscriptions_survive_reload(hass: HomeAssistant, notify_calls) -> None:
    """Expiration state persists across integration reloads."""
    set_all_off(hass)
    hass.states.async_set(TAG_ENTITY, "unknown", {"tag_id": TAG_ID})
    entry = make_entry(
        **{
            CONF_NFC_TAG: TAG_ENTITY,
            CONF_NFC_DEVICES: {PHONE: DEVICE_ID},
        }
    )
    await setup_entry(hass, entry)
    hass.bus.async_fire("tag_scanned", {"tag_id": TAG_ID, "device_id": DEVICE_ID})
    await settle(hass)
    assert entry.runtime_data.notifier.eligible_recipients() == [PHONE]
    await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)
    assert entry.runtime_data.notifier.eligible_recipients() == [PHONE]


async def _washer_finishes(hass: HomeAssistant) -> None:
    hass.states.async_set(WASHER, "on")
    await settle(hass)
    hass.states.async_set(WASHER, "off")
    await settle(hass)
