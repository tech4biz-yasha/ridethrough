"""Tests for two false passes found during validation of the approved rule.

A false pass is the worst failure a conformance tool can have: it tells an
operator they comply when they do not. Both of these were in shipped code
and both were found by hand-checking a sweep that looked non-monotonic, not
by the test suite.
"""

from dataclasses import replace

import pytest

from ridethrough.archetypes import (
    SERVER_PSU,
    UPS_DC_BUS,
    double_conversion_ups,
    no_ups,
    ups_with_battery,
)
from ridethrough.codes import ENERGINET, ERCOT
from ridethrough.facility import rectangular_sag, simulate
from ridethrough.grade import NOT_REQUIRED, RIDES_THROUGH, TRIPS, Trace, grade

RATED = 50e6


def run(f, depth, duration, total=5.0):
    return simulate(f, rectangular_sag(depth, duration, 0.5), duration_s=total)


def graded(tr, code=ERCOT):
    return grade(
        tr.voltage, tr.connected, tr.active_power, tr.current,
        tr.pre_disturbance_power, tr.max_normal_current, code=code,
    )


def check(r, name):
    return next((c for c in r.checks if c.name == name), None)


# --- false pass one: a locked-out supply drawing refill current ---------

def test_a_supply_in_lockout_draws_nothing():
    """A power supply in undervoltage lockout is off. It does not draw
    rated current to rebuild its own store while its load is switched off.

    Before this was fixed the model put a single-sample spike to 1.37 times
    rated power into the trace at the moment voltage recovered, and the
    grader read that spike as a return to 90% of pre-disturbance
    consumption.
    """
    traces = run(no_ups(RATED), 0.00, 0.15)
    assert traces.trip_driver == "server PSU undervoltage lockout"
    after = [
        traces.active_power.at(t)
        for t in traces.active_power.times
        if t >= 0.65
    ]
    assert max(after) < 0.5 * traces.pre_disturbance_power


def test_a_total_outage_now_fails_recovery():
    """The direct consequence. A site whose supplies lock out for two
    minutes cannot be back to 90% within two seconds."""
    r = graded(run(no_ups(RATED), 0.00, 0.15))
    assert r.verdict == TRIPS
    assert check(r, "power recovery").passed is False


@pytest.mark.parametrize("depth,duration", [
    (0.50, 0.5), (0.45, 0.25), (0.35, 0.25), (0.30, 0.15), (0.00, 0.15),
])
def test_the_unprotected_site_fails_every_deep_corner(depth, duration):
    """The sweep must be monotonic in depth. It was not: the site failed at
    0.30 pu and passed at 0.00 pu, which is what exposed the bug."""
    assert graded(run(no_ups(RATED), depth, duration)).verdict == TRIPS


# --- false pass two: a recharge transient read as recovery --------------

def test_recovery_means_a_level_not_a_transient():
    """A UPS rebuilding its DC bus draws heavily for a short time while the
    load it serves is still off. That is real consumption from the grid but
    it is not the facility returning to its consumption level.
    """
    traces = run(double_conversion_ups(RATED), 0.45, 0.25)
    assert traces.trip_driver == "UPS DC bus collapse"
    r = graded(traces)
    assert check(r, "power recovery").passed is False
    assert r.verdict == TRIPS


def test_reaches_and_holds_rejects_a_burst():
    """Reached inside the window but gone by the time the window closes."""
    burst = Trace([0.0, 1.0, 1.05, 1.1, 5.0], [10.0, 100.0, 100.0, 10.0, 10.0])
    assert burst.reaches_and_holds(90.0, after=1.0, by=2.0) is None


def test_reaches_and_holds_accepts_a_real_return():
    real = Trace([0.0, 1.0, 1.5, 5.0], [10.0, 10.0, 100.0, 100.0])
    assert real.reaches_and_holds(90.0, after=1.0, by=2.0) == 1.5


def test_reaches_and_holds_rejects_arriving_after_the_window():
    late = Trace([0.0, 1.0, 4.0, 8.0], [10.0, 10.0, 100.0, 100.0])
    assert late.reaches_and_holds(90.0, after=1.0, by=2.0) is None


@pytest.mark.parametrize("depth,duration", [
    (0.80, 2.0), (0.75, 0.5), (0.50, 0.5), (0.45, 0.25), (0.00, 0.15),
])
def test_the_battery_free_ups_fails_every_corner_it_cannot_hold(depth, duration):
    """Also monotonic. A 50 ms DC bus with no battery cannot hold any of
    these, and the sweep previously showed it passing four of them."""
    total = max(5.0, duration + 3.0)
    traces = run(double_conversion_ups(RATED), depth, duration, total=total)
    assert graded(traces).verdict == TRIPS


# --- the recharge rate, and what it does to Energinet -------------------

def test_recharge_defaults_to_the_current_limit():
    """The default is the fastest a facility could refill, which is the
    worst case for any overshoot obligation."""
    assert UPS_DC_BUS.recharge_limit_pu is None
    assert SERVER_PSU.recharge_limit_pu is None


def test_unconstrained_recharge_breaches_the_energinet_overshoot_limit():
    """A finding, not a bug. Energinet Section 12(2)(d) caps overshoot at
    10% of rated power above the pre-incident level in the first five
    seconds. A UPS that rebuilds its bus at its full 1.2 pu current limit
    exceeds that.

    The same event is outside ERCOT's envelope altogether, because
    0.61 pu held just under a second exceeds the 0.5 seconds allowed in the
    0.50 to 0.80 band. One event, required under one code and not the
    other.
    """
    traces = run(ups_with_battery(RATED), 0.61, 0.999)
    assert traces.active_power.maximum() / traces.pre_disturbance_power == (
        pytest.approx(1.2, abs=0.01)
    )
    assert graded(traces, ENERGINET).verdict == TRIPS
    assert graded(traces, ENERGINET).trip_driver.startswith("overshoot")
    assert graded(traces, ERCOT).verdict == NOT_REQUIRED


def test_a_stated_recharge_rate_keeps_the_facility_inside_the_limit():
    gentle = replace(
        ups_with_battery(RATED), ups=replace(UPS_DC_BUS, recharge_limit_pu=1.05)
    )
    traces = run(gentle, 0.61, 0.999)
    assert traces.active_power.maximum() / traces.pre_disturbance_power <= 1.06
    assert graded(traces, ENERGINET).verdict == RIDES_THROUGH
