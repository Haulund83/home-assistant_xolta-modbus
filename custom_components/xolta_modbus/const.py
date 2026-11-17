"""Constants for the Xolta local Modbus integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "xolta_modbus"
README_URL: Final = (
    "https://github.com/Haulund83/home-assistant_xolta-modbus#before-you-start-3-steps"
)

# Repair issues (connection lost for a while, or Modbus not open)
ISSUE_MODBUS_CLOSED: Final = "modbus_closed"
ISSUE_UNREACHABLE: Final = "controller_unreachable"
ISSUE_AFTER: Final = timedelta(minutes=10)

CONF_ALLOW_WRITE: Final = "allow_write"
CONF_UNIT_ID: Final = "unit_id"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_REPEAT_INTERVAL: Final = "repeat_interval"

DEFAULT_PORT: Final = 502
DEFAULT_UNIT_ID: Final = 1
DEFAULT_SCAN_INTERVAL: Final = 10  # seconds
DEFAULT_REPEAT_INTERVAL: Final = 20  # seconds; the cloud resets the mode after ~90 s
DEFAULT_OVERRIDE_HOURS: Final = 4.0

OVERRIDE_AUTO: Final = "auto"
OVERRIDE_STOP: Final = "stop"
OVERRIDE_SELF_CONSUMPTION: Final = "self_consumption"
OVERRIDE_OPTIONS: Final = [OVERRIDE_AUTO, OVERRIDE_STOP, OVERRIDE_SELF_CONSUMPTION]

# "Cloud has taken over" detection: the battery moves against the override.
CONTESTED_POWER_KW: Final = 0.5
CONTESTED_SECONDS: Final = {OVERRIDE_STOP: 60, OVERRIDE_SELF_CONSUMPTION: 120}

# Entity keys that only exist when writing is allowed (removed otherwise).
WRITE_ENTITY_KEYS: Final = ("override", "override_duration", "override_ends", "override_contested")

SERVICE_SET_OVERRIDE: Final = "set_override"
ATTR_MODE: Final = "mode"
ATTR_DURATION: Final = "duration"
