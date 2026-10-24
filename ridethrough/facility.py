"""A facility model, in the form the ride-through question actually needs.

The chain is grid, then optionally a UPS, then the server power supplies,
then the IT load. Cooling hangs off the IT load with a thermal lag.

Each energy store is modelled as a capacitor with a stated hold-up time, not
a stated capacitance, because hold-up time is what a facility can actually
tell you and what NERC asks operators to inventory. Capacitance is derived:

    E = 0.5 C V^2
    hold-up from nominal to the cut-off, at rated power:
        t = C (V_nom^2 - V_cut^2) / (2 P)
    so
        C = 2 P t / (V_nom^2 - V_cut^2)

Every stage draws constant power, which is the whole reason data centres are
hard on a grid: as voltage falls, current rises to hold power. That is what
runs a facility into the current ceiling. The stage's input current limit is
what stops it, and the shortfall then comes out of the energy store.

What this model does not do, stated plainly because it bounds every number it
produces: it is an averaged model. It carries energy and power at the
millisecond scale. It does not resolve point-on-wave switching, harmonics,
phase imbalance or sub-cycle protection behaviour. For the ride-through
question, which lives between ten milliseconds and a few seconds, that is the
right resolution. For anything faster it is the wrong tool.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from .grade import Trace

# Why a run stops carrying load. These are the trip drivers the model reports.
PSU_UNDERVOLTAGE = "server PSU undervoltage lockout"
UPS_BUS_COLLAPSE = "UPS DC bus collapse"
BATTERY_DEPLETED = "battery depleted"
PROTECTION_TRIP = "undervoltage protection trip"
SAG_COUNT_TRIP = "sag-counting scheme trip"


@dataclass(frozen=True)
class Stage:
    """One power conversion stage with an energy store on its DC side.

    hold_up_seconds is measured at rated power, from nominal DC voltage down
    to the cut-off voltage. current_limit_pu is the most input current the
    stage will draw, as a multiple of its current at rated power and nominal
    input voltage.
    """

    name: str
    hold_up_seconds: float
    nominal_dc_volts: float
    cutoff_dc_volts: float
    current_limit_pu: float
    restart_seconds: float = 0.0

    def capacitance(self, rated_power_w: float) -> float:
        span = self.nominal_dc_volts**2 - self.cutoff_dc_volts**2
        if span <= 0:
            raise ValueError(f"{self.name}: cut-off must be below nominal")
        return 2.0 * rated_power_w * self.hold_up_seconds / span

    def full_energy(self, rated_power_w: float) -> float:
        return 0.5 * self.capacitance(rated_power_w) * self.nominal_dc_volts**2

    def cutoff_energy(self, rated_power_w: float) -> float:
        return 0.5 * self.capacitance(rated_power_w) * self.cutoff_dc_volts**2

    def voltage_at(self, energy_j: float, rated_power_w: float) -> float:
        cap = self.capacitance(rated_power_w)
        return math.sqrt(max(0.0, 2.0 * energy_j / cap))


@dataclass(frozen=True)
class Battery:
    """Battery on the UPS DC bus.

    It engages when the bus falls to engage_fraction of nominal, after
    transfer_seconds, and can hold the bus for up to energy_seconds at rated
    power.
    """

    energy_seconds: float
    transfer_seconds: float = 0.002
    engage_fraction: float = 0.95


@dataclass(frozen=True)
class Protection:
    """Undervoltage relay at the service delivery point.

    pickup_pu of 0.0 disables it. A facility with no undervoltage trip is a
    valid configuration and some sites run that way.
    """

    pickup_pu: float = 0.0
    delay_seconds: float = 0.0


@dataclass(frozen=True)
class Facility:
    name: str
    rated_power_w: float
    psu: Stage
    ups: Stage | None = None
    battery: Battery | None = None
    protection: Protection = field(default_factory=Protection)
    cooling_fraction: float = 0.25
    cooling_tau_seconds: float = 20.0
    reduces_load_with_voltage: bool = False
    # Some UPS control schemes transfer the facility to backup after a count
    # of disturbances in a window. That is what happened in northern Virginia,
    # and ERCOT Section 2.14(2)(6) now forbids it for sags the facility is
    # required to ride through. None means no such scheme.
    sag_count_trip: int | None = None
    sag_count_window_s: float = 60.0
    notes: str = ""

    @property
    def it_power_w(self) -> float:
        return self.rated_power_w * (1.0 - self.cooling_fraction)

    @property
    def cooling_power_w(self) -> float:
        return self.rated_power_w * self.cooling_fraction


@dataclass
class RunTraces:
    """What the simulation produced, in the shape the grader consumes."""

    voltage: Trace
    connected: Trace
    active_power: Trace
    current: Trace
    pre_disturbance_power: float
    max_normal_current: float
    trip_driver: str | None = None
    trip_time: float | None = None
    psu_bus_volts: Trace | None = None
    ups_bus_volts: Trace | None = None

    def as_run(self, name: str) -> dict:
        def pack(trace: Trace) -> dict:
            return {"times": list(trace.times), "values": list(trace.values)}

        run = {
            "name": name,
            "pre_disturbance_power": self.pre_disturbance_power,
            "max_normal_current": self.max_normal_current,
            "voltage": pack(self.voltage),
            "connected": pack(self.connected),
            "active_power": pack(self.active_power),
            "current": pack(self.current),
        }
        if self.trip_driver:
            run["model_trip_driver"] = self.trip_driver
            run["model_trip_time"] = self.trip_time
        return run


def rectangular_sag(depth_pu: float, duration_s: float, start_s: float = 0.5):
    """A voltage profile: nominal, then a flat sag, then nominal again."""

    def profile(t: float) -> float:
        if start_s <= t < start_s + duration_s:
            return depth_pu
        return 1.0

    return profile


def repeated_sags(
    depth_pu: float,
    duration_s: float,
    count: int,
    interval_s: float,
    start_s: float = 0.5,
):
    """A train of identical sags at a fixed interval."""
    if count < 1:
        raise ValueError("count must be at least 1")
    times = [start_s + i * interval_s for i in range(count)]
    return reclosing_sequence(depth_pu, duration_s, times)


def reclosing_sequence(
    depth_pu: float,
    duration_s: float,
    sag_times_s: list[float],
):
    """Sags at the times given, which is what reclosing actually produces.

    A recloser does not fire at a fixed interval. It fires instantaneously,
    then after its first delay, then after its second. The gaps are uneven
    and the uneven gaps are the point, because a scheme that counts sags
    inside a window behaves differently depending on where the window falls.
    """
    if not sag_times_s:
        raise ValueError("give at least one sag time")
    times = sorted(sag_times_s)

    def profile(t: float) -> float:
        for begin in times:
            if begin <= t < begin + duration_s:
                return depth_pu
        return 1.0

    return profile


def dominion_july_2024(depth_pu: float = 0.683, duration_s: float = 0.075):
    """The sag pattern reported for the 10 July 2024 Dominion event.

    Figures are transcribed from Dominion Energy, "An Overview of Data
    Centers Response to the Recent Large Load Events in Dominion Energy",
    Narges Ghiasi and Francisco A Zelaya, presented to the ERCOT Large Load
    Working Group on 15 October 2026. That deck reports six voltage sags for
    most data centres, a minimum sag magnitude of 68.3% and a maximum sag
    duration of 75 ms, and describes the sequence as the initial fault and
    instantaneous reclosing, then reclosing at 20 seconds and 80 seconds.

    The six sag times below are our reading of that description: a pair at
    each stage, the fault and the reclose onto it. The deck gives the count,
    the magnitude, the duration and the reclosing delays. It does not give
    the individual sag timestamps, so the pairing is ours and is the one
    thing in this scenario that is not transcribed.

    This is the published sag pattern, not a model of any named facility.
    Nothing here reproduces the behaviour of a specific data centre.
    """
    start = 0.5
    return reclosing_sequence(
        depth_pu,
        duration_s,
        [
            start,
            start + 0.5,
            start + 20.0,
            start + 20.5,
            start + 80.0,
            start + 80.5,
        ],
    )


def simulate(
    facility: Facility,
    voltage: Callable[[float], float],
    duration_s: float = 5.0,
    dt: float = 1e-4,
) -> RunTraces:
    """Run the facility against a voltage profile at the service delivery point.

    Returns traces at millisecond resolution, downsampled where nothing moves.
    """
    if dt <= 0:
        raise ValueError("dt must be positive")
    if duration_s <= 0:
        raise ValueError("duration must be positive")

    rated = facility.rated_power_w
    it_rated = facility.it_power_w
    cooling_rated = facility.cooling_power_w

    psu_energy = facility.psu.full_energy(it_rated)
    psu_cutoff = facility.psu.cutoff_energy(it_rated)
    psu_full = psu_energy

    has_ups = facility.ups is not None
    if has_ups:
        ups_energy = facility.ups.full_energy(rated)
        ups_cutoff = facility.ups.cutoff_energy(rated)
        ups_full = ups_energy
    else:
        ups_energy = ups_cutoff = ups_full = 0.0

    battery_energy = (
        facility.battery.energy_seconds * rated if facility.battery else 0.0
    )

    times: list[float] = []
    v_grid_out: list[float] = []
    connected_out: list[float] = []
    power_out: list[float] = []
    current_out: list[float] = []
    psu_v_out: list[float] = []
    ups_v_out: list[float] = []

    connected = True
    psu_off_until: float | None = None
    cooling_power = cooling_rated
    under_since: float | None = None
    trip_driver: str | None = None
    trip_time: float | None = None
    battery_engaged_at: float | None = None
    ups_collapsed = False
    sag_times: list[float] = []
    in_sag = False

    steps = int(round(duration_s / dt))
    sample_every = max(1, int(round(1e-3 / dt)))

    for step in range(steps + 1):
        t = step * dt
        v = max(0.0, voltage(t))

        # A scheme that counts sags and transfers after too many.
        if facility.sag_count_trip is not None and connected:
            if v < 0.90 and not in_sag:
                in_sag = True
                sag_times.append(t)
                window = [
                    s for s in sag_times if t - s <= facility.sag_count_window_s
                ]
                if len(window) >= facility.sag_count_trip:
                    connected = False
                    if trip_driver is None:
                        trip_driver, trip_time = SAG_COUNT_TRIP, t
            elif v >= 0.90:
                in_sag = False

        # Undervoltage protection at the service delivery point.
        if connected and facility.protection.pickup_pu > 0.0:
            if v < facility.protection.pickup_pu:
                if under_since is None:
                    under_since = t
                elif t - under_since >= facility.protection.delay_seconds:
                    connected = False
                    if trip_driver is None:
                        trip_driver, trip_time = PROTECTION_TRIP, t
            else:
                under_since = None

        # What the IT load is asking for.
        if psu_off_until is not None and t < psu_off_until:
            it_demand = 0.0
        elif facility.reduces_load_with_voltage and v < 0.9:
            it_demand = it_rated * max(0.0, min(1.0, v / 0.9))
        else:
            it_demand = it_rated

        # Voltage presented to the PSUs: the UPS output, or the grid.
        # A double conversion UPS regulates its output flat until its DC bus
        # reaches cut-off, at which point the inverter shuts down. It does
        # not droop gracefully, and it stays down until the bus is rebuilt.
        if has_ups:
            if ups_collapsed:
                if ups_energy >= 0.95 * ups_full:
                    ups_collapsed = False
            elif ups_energy <= ups_cutoff:
                ups_collapsed = True
                if trip_driver is None:
                    trip_driver, trip_time = UPS_BUS_COLLAPSE, t
            psu_input_pu = 0.0 if ups_collapsed else 1.0
        else:
            psu_input_pu = v if connected else 0.0

        # PSU stage: constant power behind a current limit, store makes up
        # the shortfall.
        psu_available = (
            psu_input_pu * facility.psu.current_limit_pu * it_rated
            if psu_input_pu > 0
            else 0.0
        )
        # Above the load, whatever headroom the current limit leaves goes
        # into refilling the store. A rectifier draws more than the load
        # after a sag to rebuild its bus, which is what lets a facility
        # survive a second sag at all.
        psu_refill = min(
            max(0.0, psu_available - it_demand), (psu_full - psu_energy) / dt
        )
        psu_draw = min(psu_available, it_demand + psu_refill)
        psu_energy += (psu_draw - it_demand) * dt
        psu_energy = min(psu_full, max(0.0, psu_energy))

        if psu_energy <= psu_cutoff and it_demand > 0.0:
            psu_off_until = t + facility.psu.restart_seconds
            if trip_driver is None:
                trip_driver, trip_time = PSU_UNDERVOLTAGE, t
            it_demand = 0.0
            psu_draw = 0.0

        restarting = psu_off_until is not None and t >= psu_off_until
        if restarting and psu_energy <= psu_cutoff:
            psu_energy = psu_full
            psu_off_until = None

        # Cooling follows the IT load through a first-order lag.
        cooling_target = cooling_rated * (
            it_demand / it_rated if it_rated > 0 else 0.0
        )
        cooling_power += (cooling_target - cooling_power) * dt / (
            facility.cooling_tau_seconds
        )

        # UPS stage, if present.
        facility_demand = psu_draw + cooling_power
        if has_ups:
            ups_available = (
                v * facility.ups.current_limit_pu * rated if connected else 0.0
            )
            ups_refill = min(
                max(0.0, ups_available - facility_demand),
                (ups_full - ups_energy) / dt,
            )
            ups_draw = min(ups_available, facility_demand + ups_refill)
            shortfall = facility_demand - min(facility_demand, ups_draw)

            battery_supply = 0.0
            if facility.battery and shortfall > 0.0:
                bus_fraction = math.sqrt(max(0.0, ups_energy / ups_full))
                if bus_fraction <= facility.battery.engage_fraction:
                    if battery_engaged_at is None:
                        battery_engaged_at = t
                    if t - battery_engaged_at >= facility.battery.transfer_seconds:
                        battery_supply = min(shortfall, battery_energy / dt)
                        battery_energy -= battery_supply * dt
                        if battery_energy <= 0.0 and trip_driver is None:
                            trip_driver, trip_time = BATTERY_DEPLETED, t

            ups_energy += (ups_draw + battery_supply - facility_demand) * dt
            ups_energy = min(ups_full, max(0.0, ups_energy))
            grid_draw = ups_draw
        else:
            grid_draw = psu_draw + cooling_power if connected else 0.0

        grid_current_pu = (grid_draw / rated) / v if (v > 1e-6 and connected) else 0.0
        limit = (facility.ups or facility.psu).current_limit_pu
        grid_current_pu = min(grid_current_pu, limit)

        if step % sample_every == 0 or step == steps:
            times.append(t)
            v_grid_out.append(v)
            connected_out.append(1.0 if connected else 0.0)
            power_out.append(grid_draw)
            current_out.append(grid_current_pu)
            psu_v_out.append(facility.psu.voltage_at(psu_energy, it_rated))
            ups_v_out.append(
                facility.ups.voltage_at(ups_energy, rated) if has_ups else 0.0
            )

    return RunTraces(
        voltage=Trace(times, v_grid_out),
        connected=Trace(times, connected_out),
        active_power=Trace(times, power_out),
        current=Trace(times, current_out),
        pre_disturbance_power=rated,
        max_normal_current=1.0,
        trip_driver=trip_driver,
        trip_time=trip_time,
        psu_bus_volts=Trace(times, psu_v_out),
        ups_bus_volts=Trace(times, ups_v_out) if has_ups else None,
    )
