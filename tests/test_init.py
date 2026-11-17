"""Tests for setup, entities and the override controller."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.xolta_modbus.const import CONF_ALLOW_WRITE, DOMAIN

from .conftest import make_entry
from .fake_xolta import FakeClient, FakeXolta

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
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_read_only_setup(hass: HomeAssistant, setup_entry) -> None:
    """Read-only by default: sensors exist, no control entities."""
    assert setup_entry.state is ConfigEntryState.LOADED
    assert float(hass.states.get(SOC).state) == pytest.approx(52.7, abs=0.01)
    assert hass.states.get(STATE).state == "running"
    assert hass.states.get(OVERRIDE) is None
    assert hass.states.get(DURATION) is None


async def test_waits_for_modbus_and_starts_by_itself(
    hass: HomeAssistant, fake_xolta: FakeXolta, freezer: FrozenDateTimeFactory
) -> None:
    """Saved before Modbus is open: repair issue, retries, then starts on its own."""
    client = FakeClient(fake_xolta)
    client.offline = "refused"
    entry = make_entry(fake_xolta.port, allow_write=False)
    entry.add_to_hass(hass)
    issues = ir.async_get(hass)
    with patch("custom_components.xolta_modbus.XoltaModbusClient", lambda *_a, **_k: client):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_RETRY
        assert issues.async_get_issue(DOMAIN, f"modbus_closed_{entry.entry_id}")

        client.offline = None  # Ebbefos opened Modbus
        # HA retries with a growing back-off; give it a few minutes of (frozen) time.
        for _ in range(6):
            await _tick(hass, freezer, 30)
            if entry.state is ConfigEntryState.LOADED:
                break
        assert entry.state is ConfigEntryState.LOADED
        assert issues.async_get_issue(DOMAIN, f"modbus_closed_{entry.entry_id}") is None
        assert hass.states.get(SOC) is not None
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_unreachable_at_startup_raises_issue(
    hass: HomeAssistant, fake_xolta: FakeXolta
) -> None:
    """Nothing at the address: a different repair issue (check IP / network)."""
    client = FakeClient(fake_xolta)
    client.offline = "timeout"
    entry = make_entry(fake_xolta.port, allow_write=False)
    entry.add_to_hass(hass)
    with (
        patch("custom_components.xolta_modbus.XoltaModbusClient", lambda *_a, **_k: client),
        patch("custom_components.xolta_modbus.modbus.async_host_present", return_value=False),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"controller_unreachable_{entry.entry_id}")


async def test_modbus_closed_later_raises_issue_after_10_min(
    hass: HomeAssistant, setup_entry, fake_client: FakeClient, freezer: FrozenDateTimeFactory
) -> None:
    """Modbus closed by e.g. a firmware update: issue after 10 min, gone when it works again."""
    issue_id = f"modbus_closed_{setup_entry.entry_id}"
    issues = ir.async_get(hass)
    fake_client.offline = "refused"
    for _ in range(30):  # 5 min
        await _tick(hass, freezer, 10)
    assert hass.states.get(SOC).state == STATE_UNAVAILABLE
    assert issues.async_get_issue(DOMAIN, issue_id) is None
    for _ in range(36):  # 6 more min
        await _tick(hass, freezer, 10)
    assert issues.async_get_issue(DOMAIN, issue_id)
    fake_client.offline = None
    await _tick(hass, freezer, 10)
    assert issues.async_get_issue(DOMAIN, issue_id) is None
    assert hass.states.get(SOC).state != STATE_UNAVAILABLE


async def test_removed_entities_are_not_created(hass: HomeAssistant, setup_entry) -> None:
    """Only verified values become entities (unverified ones stay in diagnostics)."""
    registry = er.async_get(hass)
    unique_ids = {
        e.unique_id.removeprefix(f"{setup_entry.entry_id}_")
        for e in er.async_entries_for_config_entry(registry, setup_entry.entry_id)
    }
    assert unique_ids == {
        "state_of_charge", "power", "dc_voltage", "dc_current",
        "cell_temperature_min", "cell_temperature_max", "cell_voltage_min", "cell_voltage_max",
        "charge_limit", "discharge_limit", "grid_frequency", "ac_voltage_l1", "ac_current_l1",
        "state", "energy_charged", "energy_discharged",
    }  # fmt: skip


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
