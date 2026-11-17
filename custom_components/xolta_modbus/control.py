"""Override controller: writes the cluster mode and keeps it in place.

How the controller behaves (measured on a live system, November 2026):
- Writing 0 (stop) stops the battery within ~9 s and held for at least 5 min.
- Writing 1 (max self-consumption) works, but the cloud writes the mode back
  to 0 after ~90 s, so the code must be repeated (default every 20 s).
- When we stop writing, the cloud takes control back by itself within a few
  minutes. "Auto" therefore writes nothing; it just stops repeating.
- The mode register (input 1001) reads 0 even while the cloud is driving the
  battery, so it cannot be used to restore a "previous" mode.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONTESTED_POWER_KW,
    CONTESTED_SECONDS,
    DEFAULT_OVERRIDE_HOURS,
    DOMAIN,
    OVERRIDE_AUTO,
    OVERRIDE_SELF_CONSUMPTION,
    OVERRIDE_STOP,
)
from .coordinator import XoltaCoordinator
from .modbus import XoltaModbusClient, XoltaModbusError
from .registers import HOLDING_MODE, WRITE_CODE_SELF_CONSUMPTION, WRITE_CODE_STOP

_LOGGER = logging.getLogger(__name__)

WRITE_CODES = {
    OVERRIDE_STOP: WRITE_CODE_STOP,
    OVERRIDE_SELF_CONSUMPTION: WRITE_CODE_SELF_CONSUMPTION,
}


class OverrideController:
    """Holds the override state shared by the select, number and sensors."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: XoltaModbusClient,
        coordinator: XoltaCoordinator,
        repeat_interval: int,
    ) -> None:
        """Initialise with no override active."""
        self.hass = hass
        self.client = client
        self.coordinator = coordinator
        self.repeat_interval = timedelta(seconds=repeat_interval)
        self.mode: str = OVERRIDE_AUTO
        self.ends_at: datetime | None = None
        self.duration_hours: float = DEFAULT_OVERRIDE_HOURS
        self.contested = False
        self.last_write: datetime | None = None
        self.last_error: str | None = None
        self._contested_since: datetime | None = None
        self._unsub_repeat: CALLBACK_TYPE | None = None
        self._unsub_end: CALLBACK_TYPE | None = None
        self._unsub_coordinator: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_start(self) -> None:
        """Start watching coordinator data for the contested check."""
        self._unsub_coordinator = self.coordinator.async_add_listener(
            self._handle_coordinator_update
        )

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        """Register an entity callback; returns the remove function."""
        self._listeners.append(update)

        @callback
        def remove() -> None:
            self._listeners.remove(update)

        return remove

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    async def async_set(self, mode: str, duration_hours: float | None = None) -> None:
        """Start, change or end an override."""
        if mode == OVERRIDE_AUTO:
            self._cancel_timers()
            self.mode = OVERRIDE_AUTO
            self.ends_at = None
            self._reset_contested()
            _LOGGER.info("Override ended; the cloud takes control back by itself")
            self._notify()
            return
        if mode not in WRITE_CODES:
            raise HomeAssistantError(f"Unknown override mode: {mode}")

        await self._write(WRITE_CODES[mode], raise_on_error=True)
        hours = duration_hours if duration_hours is not None else self.duration_hours
        self._cancel_timers()
        self.mode = mode
        self.ends_at = dt_util.utcnow() + timedelta(hours=hours)
        self._reset_contested()
        self._unsub_repeat = async_track_time_interval(
            self.hass, self._async_repeat, self.repeat_interval
        )
        self._unsub_end = async_track_point_in_utc_time(self.hass, self._async_expire, self.ends_at)
        _LOGGER.info("Override %s active until %s", mode, self.ends_at.isoformat())
        self._notify()
        await self.coordinator.async_request_refresh()

    async def _write(self, code: int, raise_on_error: bool) -> None:
        try:
            await self.client.write_register(HOLDING_MODE, code)
        except XoltaModbusError as err:
            self.last_error = str(err)
            if raise_on_error:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="write_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            _LOGGER.warning("Repeating the override failed: %s", err)
            return
        self.last_write = dt_util.utcnow()
        self.last_error = None

    async def _async_repeat(self, _now: datetime) -> None:
        if self.mode in WRITE_CODES:
            await self._write(WRITE_CODES[self.mode], raise_on_error=False)

    async def _async_expire(self, _now: datetime) -> None:
        self._unsub_end = None
        await self.async_set(OVERRIDE_AUTO)

    def _cancel_timers(self) -> None:
        if self._unsub_repeat:
            self._unsub_repeat()
            self._unsub_repeat = None
        if self._unsub_end:
            self._unsub_end()
            self._unsub_end = None

    def _reset_contested(self) -> None:
        self.contested = False
        self._contested_since = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Flag when the battery moves against the active override."""
        data = self.coordinator.data or {}
        power = data.get("power")
        against = False
        if power is not None and self.mode == OVERRIDE_STOP:
            against = abs(power) > CONTESTED_POWER_KW
        elif power is not None and self.mode == OVERRIDE_SELF_CONSUMPTION:
            against = power < -CONTESTED_POWER_KW  # charging while it should cover the house
        now = dt_util.utcnow()
        if not against:
            changed = self.contested
            self._reset_contested()
        else:
            self._contested_since = self._contested_since or now
            limit = timedelta(seconds=CONTESTED_SECONDS[self.mode])
            new = now - self._contested_since >= limit
            changed = new != self.contested
            self.contested = new
        if changed:
            self._notify()

    def as_dict(self) -> dict[str, Any]:
        """Diagnostics."""
        return {
            "mode": self.mode,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "duration_hours": self.duration_hours,
            "repeat_interval_s": self.repeat_interval.total_seconds(),
            "contested": self.contested,
            "last_write": self.last_write.isoformat() if self.last_write else None,
            "last_error": self.last_error,
        }

    @callback
    def async_shutdown(self) -> None:
        """Stop all timers. Nothing is written: the cloud takes over again."""
        self._cancel_timers()
        if self._unsub_coordinator:
            self._unsub_coordinator()
            self._unsub_coordinator = None
