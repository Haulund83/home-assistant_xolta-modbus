"""Binary sensors for the Xolta battery."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import XoltaConfigEntry
from .entity import XoltaControlEntity, XoltaEntity

PARALLEL_UPDATES = 0

BINARY_SENSORS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(key="fully_charged", translation_key="fully_charged"),
    BinarySensorEntityDescription(key="fully_discharged", translation_key="fully_discharged"),
    BinarySensorEntityDescription(
        key="cell_balancing_needed",
        translation_key="cell_balancing_needed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="auto_cell_balancing",
        translation_key="auto_cell_balancing",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XoltaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add binary sensors."""
    runtime = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        XoltaBinarySensor(runtime.coordinator, d) for d in BINARY_SENSORS
    ]
    if runtime.controller:
        entities.append(XoltaContestedSensor(entry, runtime.controller))
    async_add_entities(entities)


class XoltaBinarySensor(XoltaEntity, BinarySensorEntity):
    """A flag read from a register."""

    def __init__(self, coordinator, description: BinarySensorEntityDescription) -> None:
        """Bind the description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the flag."""
        return self.coordinator.data.get(self.entity_description.key)


class XoltaContestedSensor(XoltaControlEntity, BinarySensorEntity):
    """On when the battery moves against the active override (the cloud took over)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "override_contested"

    def __init__(self, entry, controller) -> None:
        """Bind the controller."""
        super().__init__(entry, controller, "override_contested")

    @property
    def is_on(self) -> bool:
        """Return True when the override is not being followed."""
        return self.controller.contested
