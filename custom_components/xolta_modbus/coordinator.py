"""Polling coordinator: two Modbus requests per update.

Also watches the connection over time. If the battery stops answering on
Modbus (for example after a Xolta software update closed the port), a repair
issue tells the user what to do, and it disappears by itself once reading
works again.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, ISSUE_AFTER, ISSUE_MODBUS_CLOSED, ISSUE_UNREACHABLE, README_URL
from .modbus import (
    XoltaExceptionResponse,
    XoltaModbusClient,
    XoltaModbusError,
    async_modbus_closed,
)
from .registers import CLUSTER_BLOCK, MAIN_BLOCK, decode

_LOGGER = logging.getLogger(__name__)


def issue_id(kind: str, entry: ConfigEntry) -> str:
    """Repair issue id for one config entry."""
    return f"{kind}_{entry.entry_id}"


def clear_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove this entry's connection issues."""
    for kind in (ISSUE_MODBUS_CLOSED, ISSUE_UNREACHABLE):
        ir.async_delete_issue(hass, DOMAIN, issue_id(kind, entry))


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
        self.has_worked = False
        self._failing_since: datetime | None = None
        self._issue_kind: str | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            main = await self.client.read_input_registers(*MAIN_BLOCK)
            cluster = await self.client.read_input_registers(*CLUSTER_BLOCK)
        except XoltaModbusError as err:
            await self._async_failed(err)
            raise UpdateFailed(f"Error reading the Xolta controller: {err}") from err
        self.has_worked = True
        self._failing_since = None
        if self._issue_kind is not None:
            _LOGGER.info("Modbus answers again; removing the repair issue")
            self._issue_kind = None
        clear_issues(self.hass, self.config_entry)
        return decode(main, cluster)

    async def _async_failed(self, err: XoltaModbusError) -> None:
        """Raise a repair issue at once during setup, or after ISSUE_AFTER when running."""
        if isinstance(err, XoltaExceptionResponse):
            return  # Modbus answers; not a connection problem
        now = dt_util.utcnow()
        self._failing_since = self._failing_since or now
        if self.has_worked and now - self._failing_since < ISSUE_AFTER:
            return
        closed = await async_modbus_closed(self.client.host, err)
        kind = ISSUE_MODBUS_CLOSED if closed else ISSUE_UNREACHABLE
        if kind == self._issue_kind:
            return
        clear_issues(self.hass, self.config_entry)
        self._issue_kind = kind
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id(kind, self.config_entry),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=kind,
            translation_placeholders={"host": self.client.host},
            learn_more_url=README_URL,
        )
