"""Tests for the config, reconfigure and options flows."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.xolta_modbus.config_flow import validate_connection
from custom_components.xolta_modbus.const import (
    CONF_ALLOW_WRITE,
    CONF_REPEAT_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DOMAIN,
)
from custom_components.xolta_modbus.modbus import XoltaConnectionError, async_host_present

from .fake_xolta import FakeXolta

VALIDATE = "custom_components.xolta_modbus.config_flow.validate_connection"
SETUP = "custom_components.xolta_modbus.async_setup_entry"


async def test_user_flow_creates_read_only_entry(hass: HomeAssistant) -> None:
    """IP + write switch is all the user enters; defaults fill in the rest."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(VALIDATE, return_value=None), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: " 192.168.1.50 ", CONF_ALLOW_WRITE: False}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "192.168.1.50"}
    assert result["options"] == {
        CONF_ALLOW_WRITE: False,
        CONF_PORT: 502,
        CONF_UNIT_ID: 1,
        CONF_SCAN_INTERVAL: 10,
        CONF_REPEAT_INTERVAL: 20,
    }


@pytest.mark.parametrize("error", ["cannot_connect", "not_xolta"])
async def test_user_flow_errors_then_recovers(hass: HomeAssistant, error: str) -> None:
    """Errors are shown on the form and the user can retry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(VALIDATE, return_value=error):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_ALLOW_WRITE: True}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}
    with patch(VALIDATE, return_value=None), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_ALLOW_WRITE: True}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_ALLOW_WRITE] is True


async def test_modbus_closed_shows_mail_and_can_wait(hass: HomeAssistant) -> None:
    """Controller there but Modbus closed: menu with the e-mail; 'wait' saves the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(VALIDATE, return_value="modbus_closed"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_ALLOW_WRITE: False}
        )
        assert result["type"] is FlowResultType.MENU
        assert result["step_id"] == "modbus_closed"
        assert result["description_placeholders"] == {"host": "192.168.1.50"}
        # Still closed: the menu comes back.
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "retry"}
        )
        assert result["type"] is FlowResultType.MENU
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "wait"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "192.168.1.50"}


async def test_modbus_closed_then_opened(hass: HomeAssistant) -> None:
    """'Test again' creates the entry once Modbus answers."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(VALIDATE, return_value="modbus_closed"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_ALLOW_WRITE: True}
        )
    with patch(VALIDATE, return_value=None), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "retry"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_ALLOW_WRITE] is True


async def test_duplicate_host_aborts(hass: HomeAssistant) -> None:
    """The same controller cannot be added twice."""
    MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "192.168.1.50"}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50", CONF_ALLOW_WRITE: False}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_changes_host(hass: HomeAssistant) -> None:
    """A new IP address can be entered without removing the integration."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "192.168.1.50"}, options={})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    with patch(VALIDATE, return_value=None), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.1.60"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.168.1.60"


async def test_options_flow(hass: HomeAssistant) -> None:
    """The write switch and advanced values can be changed later."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_HOST: "192.168.1.50"}, options={CONF_ALLOW_WRITE: False}
    )
    entry.add_to_hass(hass)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_ALLOW_WRITE: True,
                CONF_SCAN_INTERVAL: 15.0,
                CONF_REPEAT_INTERVAL: 25.0,
                CONF_PORT: 502.0,
                CONF_UNIT_ID: 1.0,
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_ALLOW_WRITE: True,
        CONF_SCAN_INTERVAL: 15,
        CONF_REPEAT_INTERVAL: 25,
        CONF_PORT: 502,
        CONF_UNIT_ID: 1,
    }


async def test_validate_connection_against_fake(fake_xolta: FakeXolta) -> None:
    """The real validation reads the main block and checks the SoC."""
    assert await validate_connection("127.0.0.1", fake_xolta.port, 1) is None
    fake_xolta.set_float(23, 250.0)
    assert await validate_connection("127.0.0.1", fake_xolta.port, 1) == "not_xolta"


async def test_validate_connection_refused() -> None:
    """Port 502 refused means the device is there but Modbus is closed."""
    server = FakeXolta()
    await server.start()
    port = server.port
    await server.stop()
    assert await validate_connection("127.0.0.1", port, 1) == "modbus_closed"


@pytest.mark.parametrize(
    ("present", "expected"), [(True, "modbus_closed"), (False, "cannot_connect")]
)
async def test_validate_connection_timeout(present: bool, expected: str) -> None:
    """Port 502 silent: the presence probe (SSH/VNC ports) decides which hint is shown."""
    with (
        patch(
            "custom_components.xolta_modbus.config_flow.XoltaModbusClient.read_input_registers",
            side_effect=XoltaConnectionError("timeout"),
        ),
        patch(
            "custom_components.xolta_modbus.modbus.async_host_present", return_value=present
        ) as probe,
    ):
        assert await validate_connection("192.0.2.10", 502, 1) == expected
    probe.assert_awaited_once_with("192.0.2.10")


async def test_host_present_probe() -> None:
    """The probe treats an open or refused port as 'present' and sends no data."""
    server = FakeXolta()
    await server.start()
    open_port = server.port
    with patch("custom_components.xolta_modbus.modbus.PRESENCE_PORTS", (open_port,)):
        assert await async_host_present("127.0.0.1")
    await server.stop()
    with patch("custom_components.xolta_modbus.modbus.PRESENCE_PORTS", (open_port,)):
        assert await async_host_present("127.0.0.1")  # refused = a device is there
    assert server.requests == 0
