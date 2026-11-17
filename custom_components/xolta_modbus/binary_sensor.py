"""Binary sensor: is the active override being followed? (only with control enabled)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import XoltaConfigEntry
from .entity import XoltaControlEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XoltaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the contested sensor."""
    controller = entry.runtime_data.controller
    assert controller is not None
    async_add_entities([XoltaContestedSensor(entry, controller)])


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
