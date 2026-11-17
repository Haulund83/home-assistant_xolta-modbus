"""Tests for setup, entities and the override controller."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.xolta_modbus.const import CONF_ALLOW_WRITE, DOMAIN

from .fake_xolta import FakeXolta

SOC = "sensor.xolta_battery_state_of_charge"
POWER = "sensor.xolta_battery_power"
STATE = "sensor.xolta_battery_state"
OVERRIDE = "select.xolta_battery_override"
DURATION = "number.xolta_battery_override_duration"
ENDS = "sensor.xolta_battery_override_ends"
CONTESTED = "binary_sensor.xolta_battery_override_not_followed"
DISCHARGED = "sensor.xolta_battery_energy_discharged"


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_read_only_setup(hass: HomeAssistant, setup_entry) -> None:
    """Read-only by default: sensors exist, no control entities."""
    assert setup_entry.state is ConfigEntryState.LOADED
    assert float(hass.states.get(SOC).state) == pytest.approx(52.7, abs=0.01)
    assert hass.states.get(STATE).state == "running"
    assert hass.states.get(OVERRIDE) is None
    assert hass.states.get(DURATION) is None


async def test_setup_retries_when_unreachable(hass: HomeAssistant) -> None:
    """If the controller is down at startup, HA retries later."""
    from .conftest import make_entry

    server = FakeXolta()
    await server.start()
    port = server.port
    await server.stop()
    entry = make_entry(port, allow_write=False)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.write
async def test_stop_override_repeats_and_ends(
    hass: HomeAssistant, setup_entry, fake_xolta: FakeXolta, freezer: FrozenDateTimeFactory
) -> None:
    """Stop writes 0, repeats every 20 s and Auto stops repeating (writes nothing)."""
    assert hass.states.get(OVERRIDE).state == "auto"
    await hass.services.async_call(
        "select", "select_option", {"entity_id": OVERRIDE, "option": "stop"}, blocking=True
    )
    assert fake_xolta.writes == [(1000, 0)]
    assert hass.states.get(OVERRIDE).state == "stop"
    assert hass.states.get(ENDS).state != STATE_UNKNOWN

    await _tick(hass, freezer, 21)
    await _tick(hass, freezer, 21)
    assert len(fake_xolta.writes) == 3

    await hass.services.async_call(
        "select", "select_option", {"entity_id": OVERRIDE, "option": "auto"}, blocking=True
    )
    await _tick(hass, freezer, 60)
    assert len(fake_xolta.writes) == 3  # nothing written on Auto
    assert hass.states.get(ENDS).state == STATE_UNKNOWN


@pytest.mark.write
async def test_service_with_duration_expires(
    hass: HomeAssistant, setup_entry, fake_xolta: FakeXolta, freezer: FrozenDateTimeFactory
) -> None:
    """set_override with a duration falls back to Auto by itself."""
    await hass.services.async_call(
        DOMAIN,
        "set_override",
        {"entity_id": OVERRIDE, "mode": "self_consumption", "duration": 0.05},
        blocking=True,
    )
    assert fake_xolta.writes[0] == (1000, 1)
    assert hass.states.get(OVERRIDE).state == "self_consumption"
    for _ in range(10):  # 10 x 20 s > 3 min
        await _tick(hass, freezer, 20)
    assert hass.states.get(OVERRIDE).state == "auto"


@pytest.mark.write
async def test_contested_when_cloud_takes_over(
    hass: HomeAssistant, setup_entry, fake_xolta: FakeXolta, freezer: FrozenDateTimeFactory
) -> None:
    """The problem sensor turns on if the battery keeps moving during Stop."""
    await hass.services.async_call(
        "select", "select_option", {"entity_id": OVERRIDE, "option": "stop"}, blocking=True
    )
    fake_xolta.set_float(25, -2.0)  # charging despite Stop
    for _ in range(4):
        await _tick(hass, freezer, 10)
    assert hass.states.get(CONTESTED).state == STATE_OFF
    for _ in range(4):
        await _tick(hass, freezer, 10)
    assert hass.states.get(CONTESTED).state == STATE_ON
    fake_xolta.set_float(25, 0.0)
    await _tick(hass, freezer, 10)
    assert hass.states.get(CONTESTED).state == STATE_OFF


async def test_energy_is_integrated(
    hass: HomeAssistant, setup_entry, fake_xolta: FakeXolta, freezer: FrozenDateTimeFactory
) -> None:
    """2 kW discharge for 60 s adds about 0.033 kWh."""
    fake_xolta.set_float(25, 2.0)
    await _tick(hass, freezer, 10)
    start = float(hass.states.get(DISCHARGED).state)
    for _ in range(6):
        await _tick(hass, freezer, 10)
    assert float(hass.states.get(DISCHARGED).state) - start == pytest.approx(2 / 60, abs=0.002)
    assert float(hass.states.get(POWER).state) == pytest.approx(2.0)


@pytest.mark.write
async def test_turning_write_off_removes_controls(
    hass: HomeAssistant, setup_entry, fake_xolta: FakeXolta
) -> None:
    """Switching writing off in the options removes the control entities."""
    registry = er.async_get(hass)
    assert registry.async_get(OVERRIDE) is not None
    hass.config_entries.async_update_entry(
        setup_entry, options={**setup_entry.options, CONF_ALLOW_WRITE: False}
    )
    await hass.async_block_till_done()
    assert registry.async_get(OVERRIDE) is None
    assert registry.async_get(DURATION) is None
    assert hass.states.get(SOC) is not None
    assert fake_xolta.writes == []
