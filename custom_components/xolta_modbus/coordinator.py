"""Polling coordinator: two Modbus requests per update."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .modbus import XoltaModbusClient, XoltaModbusError
from .registers import CLUSTER_BLOCK, MAIN_BLOCK, decode

_LOGGER = logging.getLogger(__name__)


class XoltaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Reads the main block (0..43) and the cluster block (1000..1003)."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: XoltaModbusClient,
        scan_interval: int,
    ) -> None:
        """Set up the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            main = await self.client.read_input_registers(*MAIN_BLOCK)
            cluster = await self.client.read_input_registers(*CLUSTER_BLOCK)
        except XoltaModbusError as err:
            raise UpdateFailed(f"Error reading the Xolta controller: {err}") from err
        return decode(main, cluster)
