"""Override duration (only created when writing is allowed)."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import XoltaConfigEntry
from .const import DEFAULT_OVERRIDE_HOURS
from .entity import XoltaControlEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XoltaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the duration number."""
    controller = entry.runtime_data.controller
    assert controller is not None
    async_add_entities([XoltaOverrideDuration(entry, controller)])


class XoltaOverrideDuration(XoltaControlEntity, RestoreNumber):
    """How long an override from the select lasts before Auto is restored."""

    _attr_translation_key = "override_duration"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0.5
    _attr_native_max_value = 24
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.BOX

    def __init__(self, entry, controller) -> None:
        """Bind the controller."""
        super().__init__(entry, controller, "override_duration")

    async def async_added_to_hass(self) -> None:
        """Restore the last chosen duration."""
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self.controller.duration_hours = float(last.native_value)
        else:
            self.controller.duration_hours = DEFAULT_OVERRIDE_HOURS

    @property
    def native_value(self) -> float:
        """Return the duration in hours."""
        return self.controller.duration_hours

    async def async_set_native_value(self, value: float) -> None:
        """Store a new duration (applies to the next override)."""
        self.controller.duration_hours = value
        self.async_write_ha_state()
