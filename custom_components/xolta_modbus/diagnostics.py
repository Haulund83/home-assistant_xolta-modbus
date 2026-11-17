"""Diagnostics (the IP address is redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import XoltaConfigEntry

TO_REDACT = {CONF_HOST, "unique_id", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: XoltaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "last_update_success": runtime.coordinator.last_update_success,
        "data": runtime.coordinator.data,
        "override": runtime.controller.as_dict() if runtime.controller else None,
    }
