"""Integration actions (services)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN
from .coordinator import LaundryController

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_COUNT = "count"
ATTR_TIMESTAMP = "timestamp"

SERVICE_MARK_DONE = "mark_done"
SERVICE_HANG_DRY = "hang_dry"
SERVICE_RESET = "reset"
SERVICE_SET_LOAD_COUNT = "set_load_count"
SERVICE_SET_LAST_COMPLETED = "set_last_completed"

BASE_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})
SET_LOAD_COUNT_SCHEMA = BASE_SCHEMA.extend(
    {vol.Required(ATTR_COUNT): vol.All(vol.Coerce(int), vol.Range(min=0))}
)
SET_LAST_COMPLETED_SCHEMA = BASE_SCHEMA.extend(
    {vol.Required(ATTR_TIMESTAMP): cv.datetime}
)


@callback
def _controller(hass: HomeAssistant, call: ServiceCall) -> LaundryController:
    """Resolve the target instance; may be omitted when only one is loaded."""
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    loaded = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if entry_id is None:
        if len(loaded) != 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="config_entry_required",
            )
        return loaded[0].runtime_data
    for entry in loaded:
        if entry.entry_id == entry_id:
            return entry.runtime_data
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="config_entry_not_found",
        translation_placeholders={"entry_id": entry_id},
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration actions."""

    async def mark_done(call: ServiceCall) -> None:
        _controller(hass, call).mark_done("action")

    async def hang_dry(call: ServiceCall) -> None:
        _controller(hass, call).hang_dry()

    async def reset(call: ServiceCall) -> None:
        _controller(hass, call).reset()

    async def set_load_count(call: ServiceCall) -> None:
        _controller(hass, call).set_loads(call.data[ATTR_COUNT])

    async def set_last_completed(call: ServiceCall) -> None:
        _controller(hass, call).set_last_completed(call.data[ATTR_TIMESTAMP])

    hass.services.async_register(DOMAIN, SERVICE_MARK_DONE, mark_done, BASE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_HANG_DRY, hang_dry, BASE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RESET, reset, BASE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_LOAD_COUNT, set_load_count, SET_LOAD_COUNT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_LAST_COMPLETED,
        set_last_completed,
        SET_LAST_COMPLETED_SCHEMA,
    )
