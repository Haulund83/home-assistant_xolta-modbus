"""Shared entity base classes."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .control import OverrideController
from .coordinator import XoltaCoordinator


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """One device per config entry (one site controller)."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Xolta battery",
        manufacturer="Xolta",
        model="Site controller (Modbus TCP)",
    )


class XoltaEntity(CoordinatorEntity[XoltaCoordinator]):
    """Entity that reads its state from the coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: XoltaCoordinator, key: str) -> None:
        """Set unique id and device."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(entry)


class XoltaControlEntity(Entity):
    """Entity that reflects the override controller."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, controller: OverrideController, key: str) -> None:
        """Set unique id and device."""
        self.controller = controller
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Follow controller changes."""
        await super().async_added_to_hass()
        self.async_on_remove(self.controller.async_add_listener(self.async_write_ha_state))
