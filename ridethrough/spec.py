"""Describe your own facility in JSON instead of picking an archetype.

The archetypes are useful for a public table. They are no use to an operator
with a real site. This reads a facility description and builds the model from
it, so a site can be graded without anyone editing Python.

Everything is specified the way a facility can actually state it: hold-up
time rather than capacitance, current limit as a multiple of normal, battery
as seconds at rated power.

    {
      "name": "Site A, 120 MW",
      "rated_power_mw": 120,
      "cooling_fraction": 0.25,
      "psu": {"hold_up_ms": 10, "current_limit_pu": 1.5, "restart_s": 120},
      // restart_s is load-bearing. It is how long the IT load stays off
      // after the PSUs hit undervoltage lockout. It defaults to 0, which
      // means an instantaneous restart and is optimistic: servers that lose
      // their power supplies do not return in milliseconds. Give it a real
      // figure or the recovery obligation will pass for the wrong reason.
      "ups": {"hold_up_ms": 50, "current_limit_pu": 1.2},
      "battery": {"minutes": 5},
      "protection": {"undervoltage_pickup_pu": 0.85, "delay_s": 0.1},
      "reduces_load_with_voltage": false,
      "sag_count_trip": null
    }

Only `name`, `rated_power_mw` and `psu` are required. Leave `ups` or
`battery` out and the model runs without them, which is itself a common and
revealing configuration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .facility import Battery, Facility, Protection, Stage

DEFAULT_NOMINAL_V = 400.0
DEFAULT_CUTOFF_RATIO = 0.80


def _stage(name: str, raw: dict[str, Any], nominal: float) -> Stage:
    if "hold_up_ms" not in raw:
        raise ValueError(f"{name}: hold_up_ms is required")
    cutoff = raw.get("cutoff_dc_volts", nominal * DEFAULT_CUTOFF_RATIO)
    return Stage(
        name=name,
        hold_up_seconds=float(raw["hold_up_ms"]) / 1000.0,
        nominal_dc_volts=float(raw.get("nominal_dc_volts", nominal)),
        cutoff_dc_volts=float(cutoff),
        current_limit_pu=float(raw.get("current_limit_pu", 1.5)),
        recharge_limit_pu=(
            float(raw["recharge_limit_pu"])
            if raw.get("recharge_limit_pu") is not None
            else None
        ),
        restart_seconds=float(raw.get("restart_s", 0.0)),
    )


def facility_from_dict(raw: dict[str, Any]) -> Facility:
    for key in ("name", "rated_power_mw", "psu"):
        if key not in raw:
            raise ValueError(f"facility description is missing {key}")

    ups_raw = raw.get("ups")
    battery_raw = raw.get("battery")
    protection_raw = raw.get("protection") or {}

    battery = None
    if battery_raw:
        if "minutes" in battery_raw:
            seconds = float(battery_raw["minutes"]) * 60.0
        elif "seconds" in battery_raw:
            seconds = float(battery_raw["seconds"])
        else:
            raise ValueError("battery: give minutes or seconds")
        battery = Battery(
            energy_seconds=seconds,
            transfer_seconds=float(battery_raw.get("transfer_ms", 2.0)) / 1000.0,
            engage_fraction=float(battery_raw.get("engage_fraction", 0.95)),
        )
    if battery and not ups_raw:
        raise ValueError("a battery sits on the UPS DC bus, so give a ups too")

    return Facility(
        name=str(raw["name"]),
        rated_power_w=float(raw["rated_power_mw"]) * 1e6,
        psu=_stage("server PSU", raw["psu"], DEFAULT_NOMINAL_V),
        ups=_stage("UPS DC bus", ups_raw, 800.0) if ups_raw else None,
        battery=battery,
        protection=Protection(
            pickup_pu=float(protection_raw.get("undervoltage_pickup_pu", 0.0)),
            delay_seconds=float(protection_raw.get("delay_s", 0.0)),
        ),
        cooling_fraction=float(raw.get("cooling_fraction", 0.25)),
        cooling_tau_seconds=float(raw.get("cooling_tau_s", 20.0)),
        reduces_load_with_voltage=bool(raw.get("reduces_load_with_voltage", False)),
        cooling_trips_below_pu=(
            float(raw["cooling_trips_below_pu"])
            if raw.get("cooling_trips_below_pu") is not None
            else None
        ),
        transfer_scheme=bool(raw.get("transfer_scheme", False)),
        sag_count_trip=raw.get("sag_count_trip"),
        sag_count_window_s=float(raw.get("sag_count_window_s", 60.0)),
        notes=str(raw.get("notes", "")),
    )


def facility_from_file(path: Path) -> Facility:
    with Path(path).open() as handle:
        return facility_from_dict(json.load(handle))
