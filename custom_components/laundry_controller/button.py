"""Button for Laundry Controller."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LaundryConfigEntry, LaundryController
from .entity import LaundryEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LaundryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([MarkDoneButton(entry.runtime_data)])


class MarkDoneButton(LaundryEntity, ButtonEntity):
    """Acknowledge finished laundry. Never resets a running appliance."""

    def __init__(self, controller: LaundryController) -> None:
        """Initialize."""
        super().__init__(controller, "mark_done")

    async def async_press(self) -> None:
        """Mark laundry as done."""
        self.controller.mark_done("button")
