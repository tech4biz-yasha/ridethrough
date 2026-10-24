"""Tests for the obligations in the approved rule.

Every expected value here is transcribed from ERCOT Nodal Operating Guide
Section 2, file 02-080126.docx, effective 1 August 2026, Sections 2.6.4 and
2.15, and from Nodal Protocols Section 2.1 as amended by NPRR1308. Both were
approved by the PUCT on 9 July 2026 in Project No. 54445.

These tests exist because earlier versions of this package were built from
an ERCOT presentation given to SPWG in February 2026, which described a
draft. Nineteen further sets of stakeholder comments followed it and six
values changed before approval.
"""

from dataclasses import replace

import pytest

from ridethrough.archetypes import SERVER_PSU, no_ups, ups_with_battery
from ridethrough.codes import ERCOT, ERCOT_2028
from ridethrough.envelope import (
    ERCOT_COOLING_EXEMPT_BELOW_PU,
    ERCOT_CURRENT_LIMIT,
    ERCOT_FREQUENCY,
    ERCOT_HIGH_VOLTAGE_TRIP_PU,
    ERCOT_MIN_SAGS,
    ERCOT_MIN_SAGS_WINDOW_SECONDS,
    ERCOT_OVERCURRENT_MAX_SECONDS,
    ERCOT_OVERVOLTAGE_SECONDS,
    ERCOT_RECOVERY_SECONDS,
    ERCOT_TRANSFER_RECOVERY_SECONDS,
    ERCOT_TRANSFER_START_SECONDS,
    ERCOT_VOLTAGE,
    LARGE_LOAD_MIN_MW,
    LCL_MIN_COMPUTATIONAL_FRACTION,
)
from ridethrough.facility import rectangular_sag, repeated_sags, simulate
from ridethrough.grade import RIDES_THROUGH, TRIPS, Trace, grade

RATED = 50e6


def run(facility, profile, total=8.0):
    return simulate(facility, profile, duration_s=total)


def graded(traces, code=ERCOT):
    return grade(
        traces.voltage,
        traces.connected,
        traces.active_power,
        traces.current,
        traces.pre_disturbance_power,
        traces.max_normal_current,
        code=code,
        pre_disturbance_cooling_power=traces.pre_disturbance_cooling_power,
        cooling_tripped=traces.cooling_tripped,
        transfer_scheme=traces.transfer_scheme,
    )


def check(result, name):
    return next((c for c in result.checks if c.name == name), None)


# --- Table A, voltage, 2.15(3) -----------------------------------------

@pytest.mark.parametrize(
    "voltage,expected",
    [
        (1.25, None),
        (1.20, 1.0),
        (1.15, 1.0),
        (1.10, float("inf")),
        (0.90, float("inf")),
        (0.89, 2.0),
        (0.80, 2.0),
        (0.79, 0.5),
        (0.50, 0.5),
        (0.49, 0.25),
        (0.35, 0.25),
        (0.34, 0.15),
        (0.00, 0.15),
    ],
)
def test_voltage_table_matches_the_published_guide(voltage, expected):
    assert ERCOT_VOLTAGE.minimum_time(voltage) == expected


@pytest.mark.parametrize(
    "freq,expected",
    [
        (63.5, None),
        (63.0, 299.0),
        (61.3, 299.0),
        (61.2, float("inf")),
        (58.8, float("inf")),
        (58.7, 299.0),
        (57.5, 299.0),
        (57.4, None),
    ],
)
def test_frequency_table_matches_the_published_guide(freq, expected):
    assert ERCOT_FREQUENCY.minimum_time(freq) == expected


def test_the_bands_removed_in_the_draft_are_gone():
    """The draft had a 0.20 pu boundary. The approved rule has 0.35."""
    assert ERCOT_VOLTAGE.minimum_time(0.25) == 0.15
    assert ERCOT_VOLTAGE.minimum_time(0.36) == 0.25


# --- scalars, 2.15(3)(d) and (e) ---------------------------------------

def test_every_scalar_matches_the_published_guide():
    assert ERCOT_CURRENT_LIMIT == 1.50
    assert ERCOT_OVERCURRENT_MAX_SECONDS == 0.5
    assert ERCOT_RECOVERY_SECONDS == 2.0
    assert ERCOT_TRANSFER_START_SECONDS == 0.25
    assert ERCOT_TRANSFER_RECOVERY_SECONDS == 0.5
    assert ERCOT_OVERVOLTAGE_SECONDS == 1.0
    assert ERCOT_COOLING_EXEMPT_BELOW_PU == 0.35
    assert ERCOT_HIGH_VOLTAGE_TRIP_PU == 1.08
    assert ERCOT_MIN_SAGS == 6
    assert ERCOT_MIN_SAGS_WINDOW_SECONDS == 90.0


def test_the_definition_thresholds_match_nprr1308():
    assert LARGE_LOAD_MIN_MW == 75.0
    assert LCL_MIN_COMPUTATIONAL_FRACTION == 0.50


def test_the_150_percent_ceiling_binds_at_two_thirds_pu():
    """A constant power load draws 1/V, so a 150% ceiling binds where
    1/V = 1.5, at 0.667 pu."""
    loose = replace(no_ups(RATED), psu=replace(SERVER_PSU, current_limit_pu=3.0))
    inside = graded(run(loose, rectangular_sag(0.70, 0.4)))
    assert check(inside, "current ceiling").passed
    assert not check(
        graded(run(loose, rectangular_sag(0.64, 0.4))), "current ceiling"
    ).passed


# --- 2.15(3)(d), the duration cap, reported but not scored --------------

def test_the_overcurrent_duration_is_reported_and_not_scored():
    """2.15(3)(d) caps the overcurrent at 0.5 s while 2.15(3)(b) requires
    consumption for up to 2 s between 0.80 and 0.90 pu. The two clauses pull
    against each other, so this grader reports the duration and declines to
    score it rather than picking a reading."""
    loose = replace(no_ups(RATED), psu=replace(SERVER_PSU, current_limit_pu=3.0))
    result = graded(run(loose, rectangular_sag(0.85, 1.9)))
    c = check(result, "overcurrent duration")
    assert c is not None
    assert c.counts is False
    assert c.passed is False
    assert result.verdict == RIDES_THROUGH


def test_an_unscored_failure_does_not_decide_the_verdict():
    loose = replace(no_ups(RATED), psu=replace(SERVER_PSU, current_limit_pu=3.0))
    result = graded(run(loose, rectangular_sag(0.85, 1.9)))
    assert result.reported()
    assert not result.failed()


# --- 2.15(3)(c)(i) and (ii), the keep-consuming floor -------------------

def test_the_keep_consuming_floor_moves_in_2028():
    assert ERCOT.keep_consuming_above_pu == 0.80
    assert ERCOT_2028.keep_consuming_above_pu == 0.50


def test_the_floor_change_is_visible_in_a_graded_run():
    """A 0.65 pu sag sits below the pre-2028 floor and above the post-2028
    one, so the obligation applies under one code and not the other."""
    traces = run(ups_with_battery(RATED), rectangular_sag(0.65, 0.4))
    assert check(graded(traces, ERCOT), "keeps consuming").passed is None
    assert check(graded(traces, ERCOT_2028), "keeps consuming").passed is True


# --- 2.15(3)(e), the load-transfer route --------------------------------

def test_the_transfer_route_is_declared_and_never_inferred():
    """A facility that drops out is not graded under 2.15(3)(e) unless it
    says it implements such a scheme. Inferring it would let an unintended
    dropout be graded against the clause written for a deliberate one."""
    plain = run(ups_with_battery(RATED), rectangular_sag(0.60, 0.4))
    assert check(graded(plain), "transfer route") is None

    declared = run(
        replace(ups_with_battery(RATED), transfer_scheme=True),
        rectangular_sag(0.60, 0.4),
    )
    assert check(graded(declared), "transfer route") is not None


def test_the_transfer_route_only_applies_below_080_pu():
    """2.15(3)(e) opens "For undervoltage deviations below 0.8 p.u.", so it
    has no bearing on the 0.80 to 0.90 band that 2.15(3)(b) governs."""
    shallow = run(
        replace(ups_with_battery(RATED), transfer_scheme=True),
        rectangular_sag(0.85, 1.9),
    )
    assert check(graded(shallow), "transfer route") is None


def test_the_transfer_route_is_scored_only_where_the_rule_invokes_it():
    """2.15(3)(c)(ii), the post-2028 rule, is the only place that invokes
    the transfer route as relief. The pre-2028 rule never mentions it, so
    whether it binds then is unsettled and the check is reported unscored."""
    traces = run(
        replace(ups_with_battery(RATED), transfer_scheme=True),
        rectangular_sag(0.60, 0.4),
    )
    assert check(graded(traces, ERCOT), "transfer route").counts is False
    assert check(graded(traces, ERCOT_2028), "transfer route").counts is True


def test_declaring_a_transfer_scheme_relieves_keep_consuming_only_after_2028():
    traces = run(
        replace(ups_with_battery(RATED), transfer_scheme=True),
        rectangular_sag(0.60, 0.4),
    )
    post = check(graded(traces, ERCOT_2028), "keeps consuming")
    assert post.passed is None
    assert "relieved" in post.detail


def test_the_transfer_deadlines_are_tighter_than_the_general_route():
    assert ERCOT.transfer.recovery_seconds < ERCOT.recovery[0].seconds
    assert ERCOT.transfer.start_seconds < ERCOT.transfer.recovery_seconds


def test_one_transfer_action_per_device_per_event():
    assert ERCOT.transfer.actions_per_device_per_event == 1


# --- 2.15(3), cooling ---------------------------------------------------

def test_cooling_may_trip_below_035_pu_and_is_then_subtracted():
    """2.15(3) lets cooling trip below 0.35 pu for any duration, and
    2.15(3)(c) subtracts the tripped cooling from pre-disturbance
    consumption when the recovery obligation is judged."""
    cooling = replace(ups_with_battery(RATED), cooling_trips_below_pu=0.35)
    traces = run(cooling, rectangular_sag(0.30, 0.15))
    assert traces.cooling_tripped is True
    c = check(graded(traces), "cooling exemption")
    assert c is not None
    assert c.passed is None


def test_cooling_is_not_subtracted_when_the_sag_stays_above_035_pu():
    cooling = replace(ups_with_battery(RATED), cooling_trips_below_pu=0.35)
    traces = run(cooling, rectangular_sag(0.50, 0.5))
    assert traces.cooling_tripped is False
    assert check(graded(traces), "cooling exemption") is None


def test_the_subtraction_changes_the_recovery_target():
    """With a quarter of the load as cooling and cooling tripped, the 90%
    target is 90% of the remaining three quarters, not of the whole."""
    voltage = Trace([0.0, 1.0, 1.15, 8.0], [1.0, 0.30, 1.0, 1.0])
    connected = Trace([0.0, 8.0], [1.0, 1.0])
    # Comes back to 75 of a 100 pre-disturbance, which is 100% of the
    # non-cooling load but only 75% of the total.
    power = Trace([0.0, 1.0, 1.15, 1.3, 8.0], [100.0, 0.0, 0.0, 75.0, 75.0])
    current = Trace([0.0, 8.0], [1.0, 1.0])

    without = grade(voltage, connected, power, current, 100.0, 1.0)
    assert check(without, "power recovery").passed is False

    with_subtraction = grade(
        voltage,
        connected,
        power,
        current,
        100.0,
        1.0,
        pre_disturbance_cooling_power=25.0,
        cooling_tripped=True,
    )
    assert check(with_subtraction, "power recovery").passed is True


# --- 2.15(7), repeated sags ---------------------------------------------

def test_six_sags_in_ninety_seconds_is_the_stated_floor():
    assert ERCOT.min_sags == 6
    assert ERCOT.min_sags_window_seconds == 90.0


def test_a_counting_scheme_that_gives_up_inside_the_window_fails():
    from ridethrough.archetypes import ups_with_sag_counter

    traces = run(
        ups_with_sag_counter(RATED),
        repeated_sags(0.65, 0.06, count=6, interval_s=12.0),
        total=120.0,
    )
    result = graded(traces)
    assert result.verdict == TRIPS
    c = check(result, "survives repeated sags")
    assert c is not None
    assert "90 s window" in c.detail


def test_a_facility_that_rides_six_sags_satisfies_the_floor():
    traces = run(
        ups_with_battery(RATED),
        repeated_sags(0.65, 0.06, count=6, interval_s=12.0),
        total=120.0,
    )
    result = graded(traces)
    assert result.verdict == RIDES_THROUGH
    assert check(result, "survives repeated sags").passed is True


# --- provenance and open questions --------------------------------------

def test_every_ercot_value_cites_the_published_guide():
    for code in (ERCOT, ERCOT_2028):
        assert "02-080126.docx" in code.source
        assert "1 August 2026" in code.source
    assert "02-080126.docx" in ERCOT_VOLTAGE.source
    assert "02-080126.docx" in ERCOT_FREQUENCY.source


def test_the_open_questions_are_carried_in_the_code():
    assert len(ERCOT.open_questions) == 4
    joined = " ".join(ERCOT.open_questions)
    assert "Table A" in joined
    assert "2.15(3)(e)(i)" in joined
    assert "2.15(3)(d)" in joined


# --- the transfer route in practice -------------------------------------

def test_a_facility_that_never_drops_satisfies_the_transfer_clause_trivially():
    """2.15(3)(e) sets deadlines for returning to the grid. A facility that
    never left it has nothing to return from.

    This is here because the first implementation failed such a facility:
    it looked for power rising after recovery and found none, because the
    power had never fallen.
    """
    traces = run(
        replace(ups_with_battery(RATED), transfer_scheme=True),
        rectangular_sag(0.60, 0.4),
    )
    c = check(graded(traces), "transfer route")
    assert c.passed is True
    assert "no transfer occurred" in c.detail
    assert graded(traces).verdict == RIDES_THROUGH


def test_the_two_routes_can_reach_opposite_answers_on_one_run():
    """A site that drops out and returns in 0.869 s satisfies the general
    two-second route in 2.15(3)(c) and fails the half-second transfer route
    in 2.15(3)(e). Which governs decides the verdict, and the rule only
    settles it after 1 January 2028.
    """
    slow = replace(
        no_ups(RATED),
        psu=replace(SERVER_PSU, restart_seconds=1.0),
        transfer_scheme=True,
    )
    traces = run(slow, rectangular_sag(0.30, 0.15))

    pre = graded(traces, ERCOT)
    assert check(pre, "power recovery").passed is True
    assert check(pre, "transfer route").passed is False
    assert check(pre, "transfer route").counts is False
    assert pre.verdict == RIDES_THROUGH
    assert pre.reported()

    post = graded(traces, ERCOT_2028)
    assert check(post, "transfer route").counts is True
    assert post.verdict == TRIPS
    assert post.trip_driver == "transfer route"
