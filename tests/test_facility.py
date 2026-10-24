"""Tests for the facility model.

Every expected time here is worked out in closed form from the stated
hold-up time and the power shortfall, then checked against the simulation.
If the model and the arithmetic ever disagree, these break.

    store lasts = hold_up_seconds / (demand_pu - available_pu)
    available_pu = voltage_pu * current_limit_pu
"""

import pytest

from ridethrough.archetypes import (
    ARCHETYPES,
    SERVER_PSU,
    UPS_DC_BUS,
    double_conversion_ups,
    no_ups,
    no_ups_with_relay,
    ups_with_battery,
)
from ridethrough.facility import (
    PROTECTION_TRIP,
    PSU_UNDERVOLTAGE,
    UPS_BUS_COLLAPSE,
    rectangular_sag,
    simulate,
)
from ridethrough.grade import RIDES_THROUGH, TRIPS, grade

SAG_START = 0.5
RATED = 50e6


def run(facility, depth, duration, total=5.0):
    return simulate(
        facility, rectangular_sag(depth, duration, SAG_START), duration_s=total
    )


def graded(traces):
    return grade(
        traces.voltage,
        traces.connected,
        traces.active_power,
        traces.current,
        traces.pre_disturbance_power,
        traces.max_normal_current,
    )


# --- the capacitance derivation ----------------------------------------

def test_capacitance_round_trips_to_the_stated_hold_up():
    power = 1000.0
    cap = SERVER_PSU.capacitance(power)
    span = SERVER_PSU.nominal_dc_volts**2 - SERVER_PSU.cutoff_dc_volts**2
    assert cap * span / (2 * power) == pytest.approx(SERVER_PSU.hold_up_seconds)


def test_cut_off_above_nominal_is_rejected():
    from ridethrough.facility import Stage

    bad = Stage("bad", 0.01, 400.0, 500.0, 1.5)
    with pytest.raises(ValueError):
        bad.capacitance(1000.0)


# --- PSU hold-up, closed form ------------------------------------------

def test_full_outage_trips_the_psu_at_its_stated_hold_up():
    traces = run(no_ups(RATED), depth=0.0, duration=1.0)
    assert traces.trip_driver == PSU_UNDERVOLTAGE
    assert traces.trip_time == pytest.approx(
        SAG_START + SERVER_PSU.hold_up_seconds, abs=2e-3
    )


@pytest.mark.parametrize("depth", [0.10, 0.30, 0.65])
def test_psu_hold_up_scales_with_the_shortfall(depth):
    available = depth * SERVER_PSU.current_limit_pu
    shortfall = 1.0 - available
    expected = SAG_START + SERVER_PSU.hold_up_seconds / shortfall
    traces = run(no_ups(RATED), depth=depth, duration=3.0)
    assert traces.trip_driver == PSU_UNDERVOLTAGE
    assert traces.trip_time == pytest.approx(expected, abs=2e-3)


def test_no_shortfall_means_no_discharge():
    # At 0.80 pu a 1.5x limited PSU can still supply 1.2x, so nothing drains.
    traces = run(no_ups(RATED), depth=0.80, duration=3.0)
    assert traces.trip_driver is None


# --- UPS DC bus, closed form -------------------------------------------

def test_ups_bus_collapses_on_its_own_arithmetic():
    depth = 0.65
    available = depth * UPS_DC_BUS.current_limit_pu
    shortfall = 1.0 - available
    expected = SAG_START + UPS_DC_BUS.hold_up_seconds / shortfall
    traces = run(double_conversion_ups(RATED), depth=depth, duration=3.0)
    assert traces.trip_driver == UPS_BUS_COLLAPSE
    assert traces.trip_time == pytest.approx(expected, abs=2e-3)


def test_battery_holds_the_bus_through_a_long_deep_sag():
    traces = run(ups_with_battery(RATED), depth=0.10, duration=0.14)
    assert traces.trip_driver is None
    assert graded(traces).verdict == RIDES_THROUGH


# --- protection --------------------------------------------------------

def test_relay_trips_at_pickup_plus_delay():
    traces = run(no_ups_with_relay(RATED), depth=0.65, duration=3.0)
    assert traces.trip_driver == PROTECTION_TRIP
    assert traces.trip_time == pytest.approx(SAG_START + 0.1, abs=2e-3)


def test_relay_above_pickup_does_not_trip():
    traces = run(no_ups_with_relay(RATED), depth=0.88, duration=3.0)
    assert traces.trip_driver != PROTECTION_TRIP


def test_sag_shorter_than_the_delay_does_not_trip_the_relay():
    traces = run(no_ups_with_relay(RATED), depth=0.65, duration=0.05)
    assert traces.trip_driver != PROTECTION_TRIP


# --- constant power behaviour ------------------------------------------

def test_current_rises_as_the_inverse_of_voltage():
    traces = run(ups_with_battery(RATED), depth=0.90, duration=0.4)
    during = traces.current.at(SAG_START + 0.2)
    assert during == pytest.approx(1.0 / 0.90, rel=0.02)


def ceiling_check(result):
    return next(c for c in result.checks if c.name == "current ceiling")


def test_ercot_note_that_125_percent_allows_constant_power_down_to_080_pu():
    """ERCOT's own slide says the 125% ceiling allows constant power for sags
    down to 0.8 pu. A constant power load draws 1/V, and 1/0.8 is exactly
    1.25, so a facility that is free to draw that much should sit on the
    ceiling at 0.80 pu and breach just below it.

    The no-UPS archetype is the right one to test this on, because its PSU
    current limit of 1.5 pu is above the ceiling. See the test below for what
    happens when the limit is under the ceiling instead.
    """
    assert ceiling_check(graded(run(no_ups(RATED), depth=0.80, duration=0.4))).passed
    assert not ceiling_check(
        graded(run(no_ups(RATED), depth=0.78, duration=0.4))
    ).passed


def test_a_limit_below_the_ceiling_can_never_breach_it():
    """A finding worth stating plainly, because it changes where a facility
    fails. The UPS archetypes limit input current to 1.2 pu, which is under
    the 1.25 pu ceiling. They therefore cannot fail the current obligation at
    any sag depth. They run out of stored energy instead.
    """
    assert UPS_DC_BUS.current_limit_pu < 1.25
    for depth in (0.78, 0.50, 0.20, 0.0):
        traces = run(double_conversion_ups(RATED), depth=depth, duration=0.4)
        assert traces.current.maximum() <= UPS_DC_BUS.current_limit_pu + 1e-9
        assert traces.current.maximum() < 1.25


def test_load_reduction_keeps_current_off_the_ceiling():
    from dataclasses import replace

    base = no_ups(RATED)
    reducing = replace(base, reduces_load_with_voltage=True)
    assert not ceiling_check(graded(run(base, depth=0.70, duration=0.4))).passed
    assert ceiling_check(graded(run(reducing, depth=0.70, duration=0.4))).passed


# --- end to end --------------------------------------------------------

def test_every_archetype_runs_and_grades():
    for make in ARCHETYPES.values():
        traces = run(make(RATED), depth=0.65, duration=0.4)
        assert graded(traces).verdict in (RIDES_THROUGH, TRIPS)


def test_a_shallow_sag_inside_the_band_is_survived_by_every_archetype():
    for make in ARCHETYPES.values():
        assert graded(run(make(RATED), depth=0.85, duration=1.9)).verdict == (
            RIDES_THROUGH
        )


def test_the_unprotected_site_fails_where_the_battery_site_passes():
    hard = dict(depth=0.65, duration=0.4)
    assert graded(run(no_ups(RATED), **hard)).verdict == TRIPS
    assert graded(run(ups_with_battery(RATED), **hard)).verdict == RIDES_THROUGH


def test_traces_are_the_shape_the_grader_consumes():
    traces = run(ups_with_battery(RATED), depth=0.65, duration=0.4)
    run_dict = traces.as_run("test")
    for key in ("voltage", "connected", "active_power", "current"):
        assert set(run_dict[key]) == {"times", "values"}
        assert len(run_dict[key]["times"]) == len(run_dict[key]["values"])


def test_bad_timestep_is_rejected():
    with pytest.raises(ValueError):
        simulate(no_ups(RATED), rectangular_sag(0.5, 0.1), dt=0.0)
