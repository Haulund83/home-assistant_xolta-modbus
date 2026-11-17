"""Sensors for the Xolta battery."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import XoltaConfigEntry
from .entity import XoltaControlEntity, XoltaEntity
from .registers import ACTIVITY_OPTIONS, STATE_CODES

PARALLEL_UPDATES = 0
MAX_INTEGRATION_GAP = timedelta(minutes=5)

DIAG = EntityCategory.DIAGNOSTIC
MEAS = SensorStateClass.MEASUREMENT


def _num(
    key: str,
    unit: str,
    device_class: SensorDeviceClass,
    precision: int,
    *,
    diagnostic: bool = True,
    enabled: bool = True,
) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=MEAS,
        suggested_display_precision=precision,
        entity_category=DIAG if diagnostic else None,
        entity_registry_enabled_default=enabled,
    )


def _enum(key: str, options: list[str], *, diagnostic: bool = True) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENUM,
        options=options,
        entity_category=DIAG if diagnostic else None,
    )


V, A, KW = UnitOfElectricPotential.VOLT, UnitOfElectricCurrent.AMPERE, UnitOfPower.KILO_WATT
SD = SensorDeviceClass

# Only values that have been checked against a live controller are exposed
# (see docs/VERIFIED.md). Everything else is kept in diagnostics only.
SENSORS: tuple[SensorEntityDescription, ...] = (
    _num("state_of_charge", PERCENTAGE, SD.BATTERY, 1, diagnostic=False),
    _num("power", KW, SD.POWER, 2, diagnostic=False),
    _enum("activity", ACTIVITY_OPTIONS, diagnostic=False),
    _num("dc_voltage", V, SD.VOLTAGE, 1),
    _num("dc_current", A, SD.CURRENT, 1),
    _num("cell_temperature_min", UnitOfTemperature.CELSIUS, SD.TEMPERATURE, 1),
    _num("cell_temperature_max", UnitOfTemperature.CELSIUS, SD.TEMPERATURE, 1),
    _num("cell_voltage_min", V, SD.VOLTAGE, 3),
    _num("cell_voltage_max", V, SD.VOLTAGE, 3),
    _num("charge_limit", KW, SD.POWER, 1),
    _num("discharge_limit", KW, SD.POWER, 1),
    _num("grid_frequency", UnitOfFrequency.HERTZ, SD.FREQUENCY, 2),
    _num("ac_voltage_l1", V, SD.VOLTAGE, 1),
    _num("ac_current_l1", A, SD.CURRENT, 1),
    _enum("state", list(STATE_CODES.values())),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XoltaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add sensors."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    entities: list[SensorEntity] = [XoltaSensor(coordinator, d) for d in SENSORS]
    entities += [
        XoltaEnergySensor(coordinator, "energy_charged", charging=True),
        XoltaEnergySensor(coordinator, "energy_discharged", charging=False),
    ]
    if runtime.controller:
        entities.append(XoltaOverrideEndsSensor(entry, runtime.controller))
    async_add_entities(entities)


class XoltaSensor(XoltaEntity, SensorEntity):
    """A value read directly from a register."""

    def __init__(self, coordinator, description: SensorEntityDescription) -> None:
        """Bind the description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        """Return the decoded register value."""
        return self.coordinator.data.get(self.entity_description.key)


class XoltaEnergySensor(XoltaEntity, RestoreSensor):
    """Charged / discharged energy, integrated from the inverter power.

    Built in so the Energy dashboard works without helpers. Gaps longer than
    five minutes (e.g. the controller was offline) are not filled in.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, key: str, charging: bool) -> None:
        """Set direction."""
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._charging = charging
        self._total = 0.0
        self._last_power: float | None = None
        self._last_time: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the running total."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            try:
                self._total = float(last.native_value or 0)
            except (TypeError, ValueError):
                self._total = 0.0
        self._attr_native_value = round(self._total, 4)

    def _directional(self, power_kw: float) -> float:
        # Inverter power: positive = discharging, negative = charging.
        return max(-power_kw, 0.0) if self._charging else max(power_kw, 0.0)

    @callback
    def _handle_coordinator_update(self) -> None:
        power = self.coordinator.data.get("power")
        now = dt_util.utcnow()
        if power is not None:
            p_now = self._directional(power)
            if self._last_power is not None and self._last_time is not None:
                gap = now - self._last_time
                if timedelta(0) < gap <= MAX_INTEGRATION_GAP:
                    hours = gap.total_seconds() / 3600
                    self._total += (self._last_power + p_now) / 2 * hours
            self._last_power, self._last_time = p_now, now
        else:
            self._last_power = self._last_time = None
        self._attr_native_value = round(self._total, 4)
        super()._handle_coordinator_update()


class XoltaOverrideEndsSensor(XoltaControlEntity, SensorEntity):
    """When the active override ends (unknown when none is active)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "override_ends"

    def __init__(self, entry, controller) -> None:
        """Bind the controller."""
        super().__init__(entry, controller, "override_ends")

    @property
    def native_value(self) -> datetime | None:
        """Return the end time."""
        return self.controller.ends_at
