"""Register map and decoding for the Xolta Modbus interface (v2.1.0).

Facts verified against a live controller (November 2026):
- Input registers 0..43 can be read in one request (44 registers).
- Input registers 1000..1003 can be read in one request.
- float32 values use two registers, big endian word and byte order.
- Inverter active power: positive = discharging, negative = charging.
- DC current has the opposite sign (positive = charging).
"""

from __future__ import annotations

import math
import struct
from typing import Any

MAIN_BLOCK = (0, 44)
CLUSTER_BLOCK = (1000, 4)

# Holding register for the cluster operating mode (FC06).
HOLDING_MODE = 1000
WRITE_CODE_STOP = 0
WRITE_CODE_SELF_CONSUMPTION = 1  # code 2 is ignored by the controller

STATE_CODES = {1: "resting", 2: "starting_stopping", 3: "running", 4: "fault"}
UNIT_STATE_CODES = {
    0: "out_of_service",
    1: "auto_charge",
    2: "cell_balancing",
    3: "balance_recovery",
    4: "cluster",
}
CLUSTER_STATE_CODES = {1: "all_resting", 3: "running", 4: "fault"}
MODE_CODES = {0: "stop", 1: "self_consumption", 2: "passive", 3: "local"}

# key -> float32 start address inside the main block
FLOAT_REGISTERS: dict[str, int] = {
    "dc_voltage": 7,
    "dc_current": 9,
    "cell_temperature_min": 11,
    "cell_temperature_max": 13,
    "cell_voltage_min": 15,
    "cell_voltage_max": 17,
    "charge_limit": 19,
    "discharge_limit": 21,
    "state_of_charge": 23,
    "power": 25,
    "reactive_power": 27,
    "grid_frequency": 29,
    "ac_voltage_l1": 31,
    "ac_voltage_l2": 33,
    "ac_voltage_l3": 35,
    "ac_current_l1": 37,
    "ac_current_l2": 39,
    "ac_current_l3": 41,
}


def _float32(regs: list[int], address: int) -> float | None:
    value = struct.unpack(">f", struct.pack(">HH", regs[address], regs[address + 1]))[0]
    return value if math.isfinite(value) else None


def decode(main: list[int], cluster: list[int]) -> dict[str, Any]:
    """Turn raw register blocks into a dict keyed like the entity descriptions."""
    data: dict[str, Any] = {
        key: _float32(main, address) for key, address in FLOAT_REGISTERS.items()
    }
    data["fully_charged"] = bool(main[0])
    data["fully_discharged"] = bool(main[1])
    data["state"] = STATE_CODES.get(main[2])
    data["unit_state"] = UNIT_STATE_CODES.get(main[3])
    data["cell_balancing_needed"] = bool(main[43])
    data["cluster_state"] = CLUSTER_STATE_CODES.get(cluster[0])
    data["mode"] = MODE_CODES.get(cluster[1])
    data["auto_cell_balancing"] = bool(cluster[3])
    data["raw"] = {
        "state": main[2],
        "unit_state": main[3],
        "cluster_state": cluster[0],
        "mode": cluster[1],
    }
    return data
