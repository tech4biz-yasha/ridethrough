"""Tests for the two grid codes and the obligations that differ between them.

Every expected value is traceable to the source named in `ridethrough/codes.py`.
"""

import pytest

from ridethrough.archetypes import ARCHETYPES, ups_with_battery, ups_with_sag_counter
from ridethrough.codes import CODES, ENERGINET, ERCOT, ERCOT_2028
from ridethrough.envelope import ENERGINET_UV_FRT, ERCOT_VOLTAGE
from ridethrough.facility import (
    SAG_COUNT_TRIP,
    rectangular_sag,
    repeated_sags,
    simulate,
)
from ridethrough.grade import (
    NOT_REQUIRED,
    RIDES_THROUGH,
    TRIPS,
    Trace,
    excursions,
    grade,
    ride_through_required,
)

RATED = 50e6


def run(facility, profile, total=5.0):
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
    )


def check(result, name):
    return next(c for c in result.checks if c.name.startswith(name))


# --- the Energinet curve, pinned to Table 2 ----------------------------

@pytest.mark.parametrize(
    "seconds,floor",
    [
        (0.00, 0.00),
        (0.14, 0.00),
        (0.15, 0.35),
        (0.54, 0.35),
        (0.55, 0.35),
        (1.50, 0.90),
        (5.00, 0.90),
    ],
)
def test_energinet_floor_matches_table_2(seconds, floor):
    assert ENERGINET_UV_FRT.floor_at(seconds) == pytest.approx(floor)


def test_energinet_ramps_linearly_between_trec2_and_trec3():
    midpoint = ENERGINET_UV_FRT.floor_at(0.55 + (1.5 - 0.55) / 2)
    assert midpoint == pytest.approx((0.35 + 0.90) / 2, abs=1e-3)


def test_energinet_permits_zero_volts_for_150_ms():
    deep = Trace([0.0, 0.5, 0.5 + 0.149, 3.0], [1.0, 0.0, 1.0, 1.0])
    assert ride_through_required(deep, ENERGINET_UV_FRT)[0] is True
    too_long = Trace([0.0, 0.5, 0.5 + 0.20, 3.0], [1.0, 0.0, 1.0, 1.0])
    assert ride_through_required(too_long, ENERGINET_UV_FRT)[0] is False


# --- where the two codes differ ----------------------------------------

def test_energinet_sets_no_current_ceiling_because_blocking_is_permitted():
    assert ENERGINET.current_limit_pu is None
    assert ENERGINET.current_blocking_allowed is True
    assert ERCOT.current_limit_pu == 1.50
    assert ERCOT.current_blocking_allowed is False


def test_energinet_recovery_is_staged_over_thirty_seconds():
    assert [(p.seconds, p.fraction) for p in ENERGINET.recovery] == [
        (5.0, 0.80),
        (20.0, 0.90),
        (30.0, 0.95),
    ]
    assert [(p.seconds, p.fraction) for p in ERCOT.recovery] == [(2.0, 0.90)]


def test_the_2028_rule_moves_the_keep_consuming_floor():
    assert ERCOT.keep_consuming_above_pu == 0.80
    assert ERCOT_2028.keep_consuming_above_pu == 0.50


def test_a_site_graded_under_one_code_is_not_graded_under_the_other():
    """A 0.85 pu sag held 1.9 s sits inside ERCOT's envelope, which allows
    2.0 s in the 0.80 to 0.90 band, and below Energinet's floor, which has
    risen past 0.85 pu well before 1.9 s. The two codes therefore disagree
    about whether ride-through is required at all."""
    profile = rectangular_sag(0.85, 1.9)
    traces = run(ARCHETYPES["no-ups"](RATED), profile, total=8.0)
    assert graded(traces, ERCOT).required is True
    assert graded(traces, ENERGINET).verdict == NOT_REQUIRED


def test_current_ceiling_is_not_applied_under_energinet():
    traces = run(ARCHETYPES["no-ups"](RATED), rectangular_sag(0.61, 0.9))
    assert check(graded(traces, ENERGINET), "current ceiling").passed is None


# --- excursion splitting -----------------------------------------------

def test_a_train_of_sags_is_several_excursions_not_one():
    traces = run(
        ups_with_battery(RATED),
        repeated_sags(0.30, 0.06, count=6, interval_s=13.0),
        total=90.0,
    )
    pieces = excursions(traces.voltage, 0.90, 1.10)
    assert len(pieces) == 6
    for piece in pieces:
        assert piece.time_below(0.90) == pytest.approx(0.06, abs=2e-3)


def test_six_short_sags_would_fail_if_summed_as_one():
    """Summed, six 60 ms sags give 360 ms below 0.50 pu, beyond the 250 ms
    the band allows. Measured separately, each one is inside the envelope.
    This is the whole reason the trace is split.
    """
    traces = run(
        ups_with_battery(RATED),
        repeated_sags(0.30, 0.06, count=6, interval_s=13.0),
        total=90.0,
    )
    assert traces.voltage.time_below(0.50) > 0.25
    required, reason = ride_through_required(traces.voltage, ERCOT_VOLTAGE)
    assert required is True
    assert "6 separate excursions" in reason


# --- the northern Virginia failure mode --------------------------------

def test_the_sag_counter_survives_any_single_sag():
    traces = run(ups_with_sag_counter(RATED), rectangular_sag(0.30, 0.06))
    assert graded(traces).verdict == RIDES_THROUGH
    assert traces.trip_driver is None


def test_the_sag_counter_fails_the_train_it_is_required_to_ride():
    traces = run(
        ups_with_sag_counter(RATED),
        repeated_sags(0.30, 0.06, count=6, interval_s=13.0),
        total=90.0,
    )
    result = graded(traces)
    assert result.verdict == TRIPS
    assert result.trip_driver == "stays connected"
    assert traces.trip_driver == SAG_COUNT_TRIP


def test_the_sag_counter_trips_on_its_fourth_sag():
    facility = ups_with_sag_counter(RATED)
    traces = run(
        facility, repeated_sags(0.30, 0.06, count=6, interval_s=13.0), total=90.0
    )
    fourth = 0.5 + (facility.sag_count_trip - 1) * 13.0
    assert traces.trip_time == pytest.approx(fourth, abs=2e-3)


def test_sags_spread_past_the_window_do_not_trip_the_counter():
    traces = run(
        ups_with_sag_counter(RATED),
        repeated_sags(0.30, 0.06, count=6, interval_s=25.0),
        total=180.0,
    )
    assert traces.trip_driver is None


# --- derived sweep corners ---------------------------------------------

def test_ercot_corners_come_from_the_table():
    corners = dict(ERCOT_VOLTAGE.corner_points())
    assert corners[0.85] == 2.0
    assert corners[0.80] == 2.0
    assert corners[0.50] == 0.5
    assert corners[0.35] == 0.25
    assert corners[0.00] == 0.15
    assert 0.20 not in corners


def test_energinet_corners_come_from_the_curve():
    corners = ENERGINET_UV_FRT.corner_points()
    depths = [d for d, _ in corners]
    assert 0.0 in depths and 0.35 in depths
    assert dict(corners)[0.0] == pytest.approx(0.149, abs=2e-3)
    assert dict(corners)[0.35] == pytest.approx(0.55, abs=2e-3)


def test_every_code_grades_every_archetype():
    for code in CODES.values():
        for make in ARCHETYPES.values():
            result = graded(run(make(RATED), rectangular_sag(0.65, 0.4)), code)
            assert result.verdict in (RIDES_THROUGH, TRIPS, NOT_REQUIRED)
            assert result.code == code.name
