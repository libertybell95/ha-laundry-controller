"""Binary sensor for Laundry Controller."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LaundryConfigEntry, LaundryController
from .entity import LaundryEntity
from .state_machine import Appliance, Phase

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LaundryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor."""
    async_add_entities([NeedsAttentionSensor(entry.runtime_data)])


class NeedsAttentionSensor(LaundryEntity, BinarySensorEntity):
    """On while finished laundry is waiting in the washer or dryer."""

    def __init__(self, controller: LaundryController) -> None:
        """Initialize."""
        super().__init__(controller, "needs_attention")

    @property
    def is_on(self) -> bool:
        """Return True if laundry is waiting."""
        return self.controller.machine.needs_attention

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Per-appliance detail (overdue is re-evaluated at each reminder check)."""
        attrs: dict[str, Any] = {}
        for appliance in Appliance:
            waiting = self.controller.machine.records[appliance].phase is Phase.DONE
            attrs[f"{appliance}_waiting"] = waiting
            attrs[f"{appliance}_overdue"] = self.controller.is_overdue(appliance)
        return attrs
