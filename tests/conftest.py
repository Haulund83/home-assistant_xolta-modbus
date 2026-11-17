"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import patch

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.xolta_modbus.const import (
    CONF_ALLOW_WRITE,
    CONF_REPEAT_INTERVAL,
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DOMAIN,
)

from .fake_xolta import FakeClient, FakeXolta

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, socket_enabled):
    """Allow custom_components and sockets (the fake controller runs on localhost)."""
    return


@pytest.fixture
async def fake_xolta() -> AsyncGenerator[FakeXolta]:
    """Start a fake controller on a free localhost port."""
    server = FakeXolta()
    await server.start()
    yield server
    await server.stop()


def make_entry(port: int, allow_write: bool) -> MockConfigEntry:
    """Config entry pointing at the fake controller."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Xolta battery",
        data={CONF_HOST: "127.0.0.1"},
        options={
            CONF_ALLOW_WRITE: allow_write,
            CONF_PORT: port,
            CONF_UNIT_ID: 1,
            CONF_SCAN_INTERVAL: 10,
            CONF_REPEAT_INTERVAL: 20,
        },
    )


@pytest.fixture
def fake_client(fake_xolta: FakeXolta) -> FakeClient:
    """Socket-free client bound to the fake controller."""
    return FakeClient(fake_xolta)


@pytest.fixture
async def setup_entry(hass: HomeAssistant, fake_xolta: FakeXolta, fake_client, request):
    """Set up the integration (read only unless the test is marked `write`)."""
    allow_write = request.node.get_closest_marker("write") is not None
    entry = make_entry(fake_xolta.port, allow_write)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.xolta_modbus.XoltaModbusClient",
        lambda *_args, **_kwargs: fake_client,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry
    if entry.state.recoverable:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
