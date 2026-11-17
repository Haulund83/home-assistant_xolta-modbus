"""Xolta battery: local Modbus TCP integration."""

from __future__ import annotations

from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ALLOW_WRITE,
    CONF_REPEAT_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_REPEAT_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    WRITE_ENTITY_KEYS,
)
from .control import OverrideController
from .coordinator import XoltaCoordinator, clear_issues
from .modbus import XoltaModbusClient

READ_PLATFORMS = [Platform.SENSOR]
WRITE_PLATFORMS = [Platform.BINARY_SENSOR, Platform.SELECT, Platform.NUMBER]


@dataclass
class XoltaRuntimeData:
    """Objects shared by the platforms of one config entry."""

    client: XoltaModbusClient
    coordinator: XoltaCoordinator
    controller: OverrideController | None
    platforms: list[Platform] = field(default_factory=list)


type XoltaConfigEntry = ConfigEntry[XoltaRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: XoltaConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    options = entry.options
    client = XoltaModbusClient(
        entry.data[CONF_HOST],
        options.get(CONF_PORT, DEFAULT_PORT),
        options.get(CONF_UNIT_ID, DEFAULT_UNIT_ID),
    )
    coordinator = XoltaCoordinator(
        hass, entry, client, options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.close()
        raise

    allow_write = options.get(CONF_ALLOW_WRITE, False)
    controller: OverrideController | None = None
    platforms = list(READ_PLATFORMS)
    if allow_write:
        controller = OverrideController(
            hass,
            client,
            coordinator,
            options.get(CONF_REPEAT_INTERVAL, DEFAULT_REPEAT_INTERVAL),
        )
        controller.async_start()
        platforms += WRITE_PLATFORMS
    else:
        _remove_write_entities(hass, entry)

    entry.runtime_data = XoltaRuntimeData(client, coordinator, controller, platforms)
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_change))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: XoltaConfigEntry) -> bool:
    """Unload a config entry. Never writes anything to the battery."""
    runtime = entry.runtime_data
    unloaded = await hass.config_entries.async_unload_platforms(entry, runtime.platforms)
    if unloaded:
        if runtime.controller:
            runtime.controller.async_shutdown()
        await runtime.client.close()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: XoltaConfigEntry) -> None:
    """Remove repair issues that belong to a deleted entry."""
    clear_issues(hass, entry)


async def _async_reload_on_change(hass: HomeAssistant, entry: XoltaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _remove_write_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop control entities left behind after writing was switched off."""
    registry = er.async_get(hass)
    suffixes = tuple(f"_{key}" for key in WRITE_ENTITY_KEYS)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id.endswith(suffixes):
            registry.async_remove(reg_entry.entity_id)
