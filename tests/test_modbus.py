"""Tests for the dependency-free Modbus client and the register decoding."""

from __future__ import annotations

import math
import struct

import pytest

from custom_components.xolta_modbus.modbus import (
    XoltaConnectionRefused,
    XoltaExceptionResponse,
    XoltaModbusClient,
)
from custom_components.xolta_modbus.registers import (
    CLUSTER_BLOCK,
    MAIN_BLOCK,
    decode,
)

from .fake_xolta import FakeXolta


async def test_read_blocks_and_decode(fake_xolta: FakeXolta) -> None:
    """Both blocks are read and decoded with the documented signs."""
    fake_xolta.set_float(25, 1.5)  # discharging
    fake_xolta.set_float(9, -30.0)
    client = XoltaModbusClient("127.0.0.1", fake_xolta.port)
    data = decode(
        await client.read_input_registers(*MAIN_BLOCK),
        await client.read_input_registers(*CLUSTER_BLOCK),
    )
    await client.close()
    assert data["state_of_charge"] == pytest.approx(52.7, abs=0.01)
    assert data["power"] == pytest.approx(1.5)
    assert data["dc_current"] == pytest.approx(-30.0)
    assert data["state"] == "running"
    assert data["unit_state"] == "cluster"
    assert data["cluster_state"] == "running"
    assert data["mode"] == "stop"
    assert data["fully_charged"] is False


async def test_out_of_range_read_raises_exception_2(fake_xolta: FakeXolta) -> None:
    """Address 44 does not exist on the controller, so 0..44 fails like the real one."""
    client = XoltaModbusClient("127.0.0.1", fake_xolta.port)
    with pytest.raises(XoltaExceptionResponse) as err:
        await client.read_input_registers(0, 45)
    assert err.value.code == 2
    # The connection is still usable afterwards.
    assert len(await client.read_input_registers(*MAIN_BLOCK)) == 44
    await client.close()


async def test_write_is_echoed(fake_xolta: FakeXolta) -> None:
    """FC06 to holding 1000 works and is mirrored to input 1001."""
    client = XoltaModbusClient("127.0.0.1", fake_xolta.port)
    await client.write_register(1000, 1)
    assert fake_xolta.writes == [(1000, 1)]
    assert (await client.read_input_registers(1000, 4))[1] == 1
    await client.close()


async def test_reconnects_after_drop(fake_xolta: FakeXolta) -> None:
    """A dropped TCP connection is re-opened transparently."""
    client = XoltaModbusClient("127.0.0.1", fake_xolta.port)
    await client.read_input_registers(*MAIN_BLOCK)
    await fake_xolta.drop_connections()
    assert len(await client.read_input_registers(*MAIN_BLOCK)) == 44
    await client.close()


async def test_connection_refused() -> None:
    """A closed port is reported as refused (Modbus probably not enabled)."""
    server = FakeXolta()
    await server.start()
    port = server.port
    await server.stop()
    client = XoltaModbusClient("127.0.0.1", port, timeout=2)
    with pytest.raises(XoltaConnectionRefused):
        await client.read_input_registers(*MAIN_BLOCK)
    await client.close()


def test_decode_handles_nan_and_unknown_codes() -> None:
    """NaN floats become None, unknown enum codes become None."""
    main = [0] * 44
    hi, lo = struct.unpack(">HH", struct.pack(">f", math.nan))
    main[23], main[24] = hi, lo
    main[2] = 9
    data = decode(main, [2, 7, 0, 0])
    assert data["state_of_charge"] is None
    assert data["state"] is None
    assert data["cluster_state"] is None
    assert data["mode"] is None
    assert data["raw"]["mode"] == 7
