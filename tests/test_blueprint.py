"""Tests for the 'stop the battery while the EV charges' blueprint."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import shutil

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .fake_xolta import FakeXolta

BLUEPRINT = (
    Path(__file__).parents[1]
    / "blueprints"
    / "automation"
    / "xolta_modbus"
    / "stop_while_ev_charging.yaml"
)
CHARGER = "sensor.ev_charger_power"
OVERRIDE = "select.xolta_modbus_override"
ACTIVITY = "sensor.xolta_modbus_charging_status"
FLAG = "input_boolean.stopped_by_ev"
POWER_REGISTER = 25  # float32, positive = discharging


@pytest.fixture
async def blueprint_dir(hass: HomeAssistant, tmp_path: Path) -> None:
    """Point Home Assistant at a config folder that holds the blueprint."""
    target = tmp_path / "blueprints" / "automation" / "xolta_modbus"
    target.mkdir(parents=True)
    shutil.copy(BLUEPRINT, target / BLUEPRINT.name)
    hass.config.config_dir = str(tmp_path)


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    for _ in range(int(seconds // 10)):
        freezer.tick(timedelta(seconds=10))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)


async def _charger(hass: HomeAssistant, kw: float) -> None:
    hass.states.async_set(CHARGER, str(kw), {"unit_of_measurement": "kW", "device_class": "power"})
    await hass.async_block_till_done()


async def _automation(hass: HomeAssistant, with_status: bool) -> None:
    await _charger(hass, 0.0)  # the charger exists (idle) before the automation starts
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"stopped_by_ev": {}}}
    )
    inputs = {
        "charger_power": CHARGER,
        "override": OVERRIDE,
        "start_above": 1.0,
        "start_minutes": 2,
        "stop_below": 0.3,
        "stop_minutes": 10,
        "max_hours": 14,
        "started_flag": FLAG,
    }
    if with_status:
        inputs |= {"battery_status": ACTIVITY, "discharge_minutes": 1}
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "id": "stop_while_ev_charging",
                    "alias": "EV",
                    "use_blueprint": {"path": f"xolta_modbus/{BLUEPRINT.name}", "input": inputs},
                }
            ]
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get("automation.ev").state == "on"


@pytest.mark.write
async def test_without_status_always_stops(
    hass: HomeAssistant,
    blueprint_dir,
    setup_entry,
    fake_xolta: FakeXolta,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Without the status input the battery is stopped even while it is idle."""
    await _automation(hass, with_status=False)
    await _charger(hass, 7.0)
    await _tick(hass, freezer, 130)
    assert hass.states.get(OVERRIDE).state == "stop"
    assert hass.states.get(FLAG).state == "on"

    await _charger(hass, 0.0)
    await _tick(hass, freezer, 610)
    assert hass.states.get(OVERRIDE).state == "auto"
    assert hass.states.get(FLAG).state == "off"


@pytest.mark.write
async def test_with_status_waits_until_the_battery_discharges(
    hass: HomeAssistant,
    blueprint_dir,
    setup_entry,
    fake_xolta: FakeXolta,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Idle or charging battery is left alone; it is stopped once it discharges."""
    await _automation(hass, with_status=True)

    fake_xolta.set_float(POWER_REGISTER, -2.0)  # the cloud charges the battery
    await _tick(hass, freezer, 10)
    assert hass.states.get(ACTIVITY).state == "charging"
    await _charger(hass, 7.0)
    await _tick(hass, freezer, 300)
    assert hass.states.get(OVERRIDE).state == "auto"

    fake_xolta.set_float(POWER_REGISTER, 1.5)  # starts discharging into the car
    await _tick(hass, freezer, 30)
    assert hass.states.get(ACTIVITY).state == "discharging"
    assert hass.states.get(OVERRIDE).state == "auto"  # not yet 1 minute
    await _tick(hass, freezer, 50)
    assert hass.states.get(OVERRIDE).state == "stop"
    assert hass.states.get(FLAG).state == "on"

    await _charger(hass, 0.0)
    await _tick(hass, freezer, 610)
    assert hass.states.get(OVERRIDE).state == "auto"


@pytest.mark.write
async def test_with_status_discharge_without_car_is_left_alone(
    hass: HomeAssistant,
    blueprint_dir,
    setup_entry,
    fake_xolta: FakeXolta,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The battery discharging on its own (car not charging) is not stopped."""
    await _automation(hass, with_status=True)
    await _charger(hass, 0.0)
    fake_xolta.set_float(POWER_REGISTER, 1.5)
    await _tick(hass, freezer, 300)
    assert hass.states.get(ACTIVITY).state == "discharging"
    assert hass.states.get(OVERRIDE).state == "auto"
