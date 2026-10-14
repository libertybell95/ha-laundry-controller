"""Switches for Laundry Controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LaundryConfigEntry, LaundryController
from .entity import LaundryEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LaundrySwitchDescription(SwitchEntityDescription):
    """Describes a laundry switch."""

    is_on_fn: Callable[[LaundryController], bool]
    set_fn: Callable[[LaundryController, bool], None]


SWITCHES: tuple[LaundrySwitchDescription, ...] = (
    LaundrySwitchDescription(
        key="reminders",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda c: c.reminders_enabled,
        set_fn=lambda c, on: c.set_reminders_enabled(on),
    ),
    LaundrySwitchDescription(
        key="announcements",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda c: c.tts_enabled,
        set_fn=lambda c, on: c.set_tts_enabled(on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LaundryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    async_add_entities(
        LaundrySwitch(entry.runtime_data, description) for description in SWITCHES
    )


class LaundrySwitch(LaundryEntity, SwitchEntity):
    """A persisted feature toggle."""

    entity_description: LaundrySwitchDescription

    def __init__(
        self, controller: LaundryController, description: LaundrySwitchDescription
    ) -> None:
        """Initialize."""
        super().__init__(controller, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        """Return the toggle state."""
        return self.entity_description.is_on_fn(self.controller)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable."""
        self.entity_description.set_fn(self.controller, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable."""
        self.entity_description.set_fn(self.controller, False)
