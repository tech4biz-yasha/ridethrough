"""Tests. Every expected value here is traceable to the ERCOT source document."""

import pytest

from ridethrough.envelope import (
    CONTINUOUS,
    ERCOT_CURRENT_LIMIT,
    ERCOT_FREQUENCY,
    ERCOT_VOLTAGE,
)
from ridethrough.grade import (
    ERROR,
    NOT_REQUIRED,
    RIDES_THROUGH,
    TRIPS,
    Trace,
    grade,
    ride_through_required,
)

# --- the table itself, pinned ------------------------------------------

@pytest.mark.parametrize(
    "voltage,expected",
    [
        (1.25, None),
        (1.15, 1.0),
        (1.00, CONTINUOUS),
        (0.85, 2.0),
        (0.65, 0.5),
        (0.40, 0.25),
        (0.10, 0.15),
    ],
)
def test_voltage_table(voltage, expected):
    assert ERCOT_VOLTAGE.minimum_time(voltage) == expected


@pytest.mark.parametrize(
    "freq,expected",
    [
        (63.5, None),
        (62.0, 299.0),
        (60.0, CONTINUOUS),
        (58.0, 299.0),
        (57.0, None),
    ],
)
def test_frequency_table(freq, expected):
    assert ERCOT_FREQUENCY.minimum_time(freq) == expected


def test_band_edges_are_closed_where_the_source_says_so():
    assert ERCOT_VOLTAGE.minimum_time(0.90) == CONTINUOUS
    assert ERCOT_VOLTAGE.minimum_time(1.10) == CONTINUOUS
    assert ERCOT_VOLTAGE.minimum_time(1.20) == 1.0
    assert ERCOT_VOLTAGE.minimum_time(0.80) == 2.0
    assert ERCOT_VOLTAGE.minimum_time(0.50) == 0.5
    assert ERCOT_VOLTAGE.minimum_time(0.35) == 0.25
    assert ERCOT_VOLTAGE.minimum_time(0.34) == 0.15


def test_current_limit_is_150_percent():
    """2.15(3)(d): 150% of maximum normal current."""
    assert ERCOT_CURRENT_LIMIT == 1.50


# --- is ride-through required ------------------------------------------

def sag(depth, duration, total=5.0):
    """A rectangular sag starting at t=1.0."""
    return Trace(
        times=[0.0, 1.0, 1.0 + duration, total],
        values=[1.0, depth, 1.0, 1.0],
    )


def test_sag_inside_the_envelope_is_required():
    required, reason = ride_through_required(sag(0.65, 0.4))
    assert required is True


def test_sag_held_past_its_band_is_not_required():
    required, reason = ride_through_required(sag(0.65, 0.9))
    assert required is False
    assert "0.80" in reason


def test_shallow_sag_gets_the_two_second_allowance():
    assert ride_through_required(sag(0.85, 1.9))[0] is True
    assert ride_through_required(sag(0.85, 2.1))[0] is False


def test_deep_sag_gets_150_ms():
    assert ride_through_required(sag(0.10, 0.14))[0] is True
    assert ride_through_required(sag(0.10, 0.20))[0] is False


def test_flat_run_is_an_error_not_a_pass():
    flat = Trace(times=[0.0, 1.0, 5.0], values=[1.0, 1.0, 1.0])
    required, reason = ride_through_required(flat)
    assert required is None
    assert "tests nothing" in reason


# --- grading a response -------------------------------------------------

def constant(value, total=5.0):
    return Trace(times=[0.0, total], values=[value, value])


def good_response(depth=0.65, duration=0.4):
    v = sag(depth, duration)
    connected = constant(1.0)
    power = Trace(
        times=[0.0, 1.0, 1.0 + duration, 1.0 + duration + 0.3, 5.0],
        values=[100.0, 60.0, 60.0, 98.0, 100.0],
    )
    current = Trace(
        times=[0.0, 1.0, 1.0 + duration, 5.0],
        values=[1.0, 1.15, 1.0, 1.0],
    )
    return v, connected, power, current


def test_clean_ride_through():
    v, c, p, i = good_response()
    r = grade(v, c, p, i, pre_disturbance_power=100.0, max_normal_current=1.0)
    assert r.verdict == RIDES_THROUGH
    assert r.trip_driver is None


def test_disconnection_is_caught():
    v, _, p, i = good_response()
    disconnected = Trace(times=[0.0, 1.05, 5.0], values=[1.0, 0.0, 0.0])
    r = grade(v, disconnected, p, i,
              pre_disturbance_power=100.0, max_normal_current=1.0)
    assert r.verdict == TRIPS
    assert r.trip_driver == "stays connected"


def test_current_over_the_ceiling_is_caught():
    v, c, p, _ = good_response()
    hot = Trace(times=[0.0, 1.0, 1.4, 5.0], values=[1.0, 1.7, 1.0, 1.0])
    r = grade(v, c, p, hot,
              pre_disturbance_power=100.0, max_normal_current=1.0)
    assert r.verdict == TRIPS
    assert r.trip_driver == "current ceiling"
    ceiling_check = next(x for x in r.checks if x.name == "current ceiling")
    assert ceiling_check.margin == pytest.approx(1.50 - 1.7)


def test_slow_recovery_is_caught():
    duration = 0.4
    v = sag(0.65, duration, total=10.0)
    c = constant(1.0, total=10.0)
    slow = Trace(
        times=[0.0, 1.0, 1.4, 5.0, 10.0],
        values=[100.0, 60.0, 60.0, 98.0, 100.0],
    )
    i = Trace(times=[0.0, 1.0, 1.4, 10.0], values=[1.0, 1.15, 1.0, 1.0])
    r = grade(v, c, slow, i,
              pre_disturbance_power=100.0, max_normal_current=1.0)
    assert r.verdict == TRIPS
    assert r.trip_driver == "power recovery"


def test_sag_outside_the_envelope_is_not_graded_as_a_failure():
    v = sag(0.10, 0.5)
    c = Trace(times=[0.0, 1.05, 5.0], values=[1.0, 0.0, 0.0])
    p = constant(0.0)
    i = constant(1.0)
    r = grade(v, c, p, i,
              pre_disturbance_power=100.0, max_normal_current=1.0)
    assert r.verdict == NOT_REQUIRED


def test_flat_run_grades_as_error():
    flat = Trace(times=[0.0, 5.0], values=[1.0, 1.0])
    r = grade(flat, constant(1.0), constant(100.0), constant(1.0),
              pre_disturbance_power=100.0, max_normal_current=1.0)
    assert r.verdict == ERROR
