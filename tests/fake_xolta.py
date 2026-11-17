"""A tiny fake Xolta site controller (Modbus TCP server) for tests.

It mimics what the real controller does:
- input registers 0..43 and 1000..1003 are readable; other ranges answer
  exception 2 (illegal data address), like the real one.
- FC06 to holding 1000 is echoed and mirrored into input 1001.
"""

from __future__ import annotations

import asyncio
import struct

READABLE = ((0, 44), (1000, 4))


class FakeXolta:
    """In-process Modbus TCP server."""

    def __init__(self) -> None:
        """Fill in plausible values (a 48 V pack, resting, 52.7 %)."""
        self.inputs: dict[int, int] = {}
        self.writes: list[tuple[int, int]] = []
        self.requests = 0
        self.port = 0
        self._server: asyncio.base_events.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self.inputs.update({0: 0, 1: 0, 2: 3, 3: 4, 43: 0, 1000: 3, 1001: 0, 1002: 0, 1003: 0})
        for addr, value in {
            7: 49.4,
            9: 0.0,
            11: 17.0,
            13: 18.5,
            15: 3.29,
            17: 3.31,
            19: 3.6,
            21: 3.6,
            23: 52.7,
            25: 0.0,
            27: 0.0,
            29: 50.0,
            31: 231.0,
            33: 0.0,
            35: 0.0,
            37: 0.0,
            39: 0.0,
            41: 0.0,
        }.items():
            self.set_float(addr, value)

    def set_float(self, address: int, value: float) -> None:
        """Store a big-endian float32 in two registers."""
        hi, lo = struct.unpack(">HH", struct.pack(">f", value))
        self.inputs[address], self.inputs[address + 1] = hi, lo

    async def start(self) -> None:
        """Listen on a free localhost port."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Close the server and every client connection."""
        if self._server is None:
            return
        self._server.close()
        await self.drop_connections()
        await self._server.wait_closed()
        self._server = None

    async def drop_connections(self) -> None:
        """Simulate the controller closing the TCP connection."""
        for writer in list(self._writers):
            writer.close()
        self._writers.clear()
        await asyncio.sleep(0)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        try:
            while True:
                header = await reader.readexactly(7)
                tid, _proto, length, unit = struct.unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
                self.requests += 1
                reply = self._process(pdu)
                writer.write(struct.pack(">HHHB", tid, 0, len(reply) + 1, unit) + reply)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    def _process(self, pdu: bytes) -> bytes:
        function = pdu[0]
        if function == 4:
            address, count = struct.unpack(">HH", pdu[1:5])
            if not any(s <= address and address + count <= s + n for s, n in READABLE):
                return bytes([function | 0x80, 2])
            regs = [self.inputs.get(a, 0) for a in range(address, address + count)]
            return bytes([function, count * 2]) + struct.pack(f">{count}H", *regs)
        if function == 6:
            address, value = struct.unpack(">HH", pdu[1:5])
            if address != 1000:
                return bytes([function | 0x80, 2])
            self.writes.append((address, value))
            self.inputs[1001] = value
            return pdu[:5]
        return bytes([function | 0x80, 1])


class FakeClient:
    """Drop-in for XoltaModbusClient that talks to FakeXolta without sockets.

    Used by the Home Assistant level tests, where frozen time and real socket
    timeouts do not mix.
    """

    def __init__(self, fake: FakeXolta) -> None:
        """Bind to the fake controller."""
        self.fake = fake
        self.host = "127.0.0.1"
        # None = online, "refused" = Modbus closed (port 502 refused), "timeout" = no answer
        self.offline: str | None = None

    def _call(self, pdu: bytes) -> bytes:
        from custom_components.xolta_modbus.modbus import (
            XoltaConnectionError,
            XoltaConnectionRefused,
            XoltaExceptionResponse,
        )

        if self.offline == "refused":
            raise XoltaConnectionRefused("refused")
        if self.offline:
            raise XoltaConnectionError("timeout")
        reply = self.fake._process(pdu)
        if reply[0] & 0x80:
            raise XoltaExceptionResponse(pdu[0], reply[1])
        return reply

    async def read_input_registers(self, address: int, count: int) -> list[int]:
        """FC04."""
        reply = self._call(struct.pack(">BHH", 4, address, count))
        return list(struct.unpack(f">{count}H", reply[2:]))

    async def write_register(self, address: int, value: int) -> None:
        """FC06."""
        self._call(struct.pack(">BHH", 6, address, value))

    async def close(self) -> None:
        """Nothing to close."""
