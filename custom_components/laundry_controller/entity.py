"""Base entity for Laundry Controller."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import LaundryController


class LaundryEntity(Entity):
    """An entity owned by a laundry controller instance."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: LaundryController, key: str) -> None:
        """Initialize."""
        self.controller = controller
        entry = controller.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Laundry Controller",
            model="Washer and dryer monitor",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to controller updates."""
        self.async_on_remove(
            self.controller.async_add_listener(self.async_write_ha_state)
        )
