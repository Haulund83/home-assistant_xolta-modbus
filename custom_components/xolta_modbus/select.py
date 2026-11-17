"""Override select (only created when writing is allowed)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
import voluptuous as vol

from . import XoltaConfigEntry
from .const import ATTR_DURATION, ATTR_MODE, OVERRIDE_OPTIONS, SERVICE_SET_OVERRIDE
from .entity import XoltaControlEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XoltaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the override select and its service."""
    controller = entry.runtime_data.controller
    assert controller is not None
    async_add_entities([XoltaOverrideSelect(entry, controller)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_OVERRIDE,
        {
            vol.Required(ATTR_MODE): vol.In(OVERRIDE_OPTIONS),
            vol.Optional(ATTR_DURATION): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=48)),
        },
        "async_set_override",
    )


class XoltaOverrideSelect(XoltaControlEntity, SelectEntity):
    """Auto / Stop / Self-consumption."""

    _attr_translation_key = "override"
    _attr_options = OVERRIDE_OPTIONS

    def __init__(self, entry, controller) -> None:
        """Bind the controller."""
        super().__init__(entry, controller, "override")

    @property
    def current_option(self) -> str:
        """Return the active override."""
        return self.controller.mode

    async def async_select_option(self, option: str) -> None:
        """Start or end an override with the default duration."""
        await self.controller.async_set(option)

    async def async_set_override(self, mode: str, duration: float | None = None) -> None:
        """Service: start or end an override with an optional duration (hours)."""
        await self.controller.async_set(mode, duration)
