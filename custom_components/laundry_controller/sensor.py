"""Sensors for Laundry Controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LaundryConfigEntry, LaundryController
from .entity import LaundryEntity
from .state_machine import PHASE_STATES, STATUS_STATES, Appliance

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LaundrySensorDescription(SensorEntityDescription):
    """Describes a laundry sensor."""

    value_fn: Callable[[LaundryController], Any]
    attrs_fn: Callable[[LaundryController], dict[str, Any]] | None = None


def _duration_minutes(
    controller: LaundryController, appliance: Appliance
) -> float | None:
    duration = controller.machine.records[appliance].last_duration
    return round(duration.total_seconds() / 60, 1) if duration else None


def _appliance_attrs(
    controller: LaundryController, appliance: Appliance
) -> dict[str, Any]:
    record = controller.machine.records[appliance]
    return {
        "started_at": _iso(record.started_at),
        "finished_at": _iso(record.finished_at),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


SENSORS: tuple[LaundrySensorDescription, ...] = (
    LaundrySensorDescription(
        key="washer_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(PHASE_STATES[Appliance.WASHER].values()),
        value_fn=lambda c: c.machine.state_of(Appliance.WASHER),
        attrs_fn=lambda c: _appliance_attrs(c, Appliance.WASHER),
    ),
    LaundrySensorDescription(
        key="dryer_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(PHASE_STATES[Appliance.DRYER].values()),
        value_fn=lambda c: c.machine.state_of(Appliance.DRYER),
        attrs_fn=lambda c: _appliance_attrs(c, Appliance.DRYER),
    ),
    LaundrySensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=list(dict.fromkeys(STATUS_STATES.values())),
        value_fn=lambda c: c.machine.status,
    ),
    LaundrySensorDescription(
        key="loads",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="loads",
        value_fn=lambda c: c.machine.loads,
    ),
    LaundrySensorDescription(
        key="last_completed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.machine.last_completed,
    ),
    LaundrySensorDescription(
        key="washer_cycle_duration",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda c: _duration_minutes(c, Appliance.WASHER),
    ),
    LaundrySensorDescription(
        key="dryer_cycle_duration",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda c: _duration_minutes(c, Appliance.DRYER),
    ),
    LaundrySensorDescription(
        key="next_reminder",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.next_reminder,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LaundryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    async_add_entities(
        LaundrySensor(entry.runtime_data, description) for description in SENSORS
    )


class LaundrySensor(LaundryEntity, SensorEntity):
    """A laundry sensor."""

    entity_description: LaundrySensorDescription

    def __init__(
        self, controller: LaundryController, description: LaundrySensorDescription
    ) -> None:
        """Initialize."""
        super().__init__(controller, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the state."""
        return self.entity_description.value_fn(self.controller)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.controller)
