"""Minimal asyncio Modbus TCP client for the Xolta site controller.

Only the two function codes the integration needs are implemented:
FC04 (read input registers) and FC06 (write single holding register).
Having no third-party dependency means the integration never conflicts
with the pymodbus version bundled with Home Assistant.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct

_LOGGER = logging.getLogger(__name__)

FC_READ_INPUT = 0x04
FC_WRITE_SINGLE = 0x06
_MBAP = struct.Struct(">HHHB")  # transaction id, protocol id, length, unit id


class XoltaModbusError(Exception):
    """Base error for Modbus communication."""


class XoltaConnectionError(XoltaModbusError):
    """The controller could not be reached or the connection broke."""


class XoltaConnectionRefused(XoltaConnectionError):
    """The controller refused the connection (Modbus is probably not enabled)."""


class XoltaExceptionResponse(XoltaModbusError):
    """The controller answered with a Modbus exception."""

    def __init__(self, function: int, code: int) -> None:
        """Store the exception code."""
        super().__init__(f"Modbus exception {code} for function {function}")
        self.function = function
        self.code = code


class XoltaModbusClient:
    """Keeps one TCP connection open and serialises all requests."""

    def __init__(self, host: str, port: int = 502, unit_id: int = 1, timeout: float = 5.0) -> None:
        """Initialise the client. No I/O happens until the first request."""
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._transaction_id = 0

    @property
    def connected(self) -> bool:
        """Return True when a connection is open."""
        return self._writer is not None and not self._writer.is_closing()

    async def _connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timeout
            )
        except ConnectionRefusedError as err:
            raise XoltaConnectionRefused(f"{self.host}:{self.port} refused the connection") from err
        except (TimeoutError, OSError) as err:
            raise XoltaConnectionError(
                f"Cannot connect to {self.host}:{self.port}: {err!r}"
            ) from err

    async def close(self) -> None:
        """Close the connection (safe to call more than once)."""
        writer, self._reader, self._writer = self._writer, None, None
        if writer is None:
            return
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()

    async def _exchange(self, pdu: bytes) -> bytes:
        if not self.connected:
            await self._connect()
        assert self._reader is not None and self._writer is not None
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        tid = self._transaction_id
        self._writer.write(_MBAP.pack(tid, 0, len(pdu) + 1, self.unit_id) + pdu)
        await self._writer.drain()
        while True:
            header = await self._reader.readexactly(_MBAP.size)
            r_tid, protocol, length, _unit = _MBAP.unpack(header)
            if length < 2 or protocol != 0:
                raise XoltaConnectionError("Malformed Modbus TCP header")
            body = await self._reader.readexactly(length - 1)
            if r_tid == tid:
                return body
            _LOGGER.debug("Dropping stale response %s (waiting for %s)", r_tid, tid)

    async def _request(self, pdu: bytes) -> bytes:
        """Send a PDU and return the response PDU. Retries once on a broken link."""
        async with self._lock:
            for attempt in (1, 2):
                try:
                    body = await asyncio.wait_for(self._exchange(pdu), self.timeout)
                    break
                except XoltaConnectionRefused:
                    await self.close()
                    raise
                except (
                    TimeoutError,
                    OSError,
                    asyncio.IncompleteReadError,
                    XoltaConnectionError,
                ) as err:
                    await self.close()
                    if attempt == 2:
                        if isinstance(err, XoltaConnectionError):
                            raise
                        raise XoltaConnectionError(
                            f"Modbus request to {self.host}:{self.port} failed: {err!r}"
                        ) from err
                    _LOGGER.debug("Modbus request failed (%r), reconnecting", err)
        function = pdu[0]
        if body[0] == function | 0x80:
            raise XoltaExceptionResponse(function, body[1] if len(body) > 1 else 0)
        if body[0] != function:
            raise XoltaConnectionError(f"Unexpected function code {body[0]}")
        return body

    async def read_input_registers(self, address: int, count: int) -> list[int]:
        """Read `count` input registers (FC04) starting at `address`."""
        body = await self._request(struct.pack(">BHH", FC_READ_INPUT, address, count))
        byte_count = body[1]
        if byte_count != count * 2 or len(body) < 2 + byte_count:
            raise XoltaConnectionError("Short read from controller")
        return list(struct.unpack(f">{count}H", body[2 : 2 + byte_count]))

    async def write_register(self, address: int, value: int) -> None:
        """Write one holding register (FC06)."""
        body = await self._request(struct.pack(">BHH", FC_WRITE_SINGLE, address, value & 0xFFFF))
        if body[1:5] != struct.pack(">HH", address, value & 0xFFFF):
            raise XoltaConnectionError("Write was not echoed by the controller")
