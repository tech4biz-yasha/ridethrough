"""Tests for Section 2.6.4, the frequency obligations.

Transcribed from ERCOT Nodal Operating Guide Section 2, file 02-080126.docx,
effective 1 August 2026, Section 2.6.4.

These exist because until now this package shipped a frequency table and
never graded anything against it, which is worse than not shipping the table
at all.
"""

import pytest

from ridethrough.codes import ENERGINET, ERCOT, ERCOT_2028
from ridethrough.envelope import (
    ERCOT_FREQUENCY,
    ERCOT_FREQUENCY_POWER_BAND,
    ERCOT_FREQUENCY_TRANSFER_SECONDS,
)
from ridethrough.grade import (
    ERROR,
    NOT_REQUIRED,
    RIDES_THROUGH,
    TRIPS,
    Trace,
    grade_frequency,
)

CONNECTED = Trace([0.0, 20.0], [1.0, 1.0])
FULL = Trace([0.0, 20.0], [100.0, 100.0])


def deviation(hz, duration, start=1.0, total=20.0):
    return Trace([0.0, start, start + duration, total], [60.0, hz, 60.0, 60.0])


def check(result, name):
    return next((c for c in result.checks if c.name == name), None)


def test_the_constants_match_the_published_guide():
    assert ERCOT_FREQUENCY_POWER_BAND == 0.10
    assert ERCOT_FREQUENCY_TRANSFER_SECONDS == 2.0


def test_a_deviation_inside_the_table_requires_ride_through():
    r = grade_frequency(deviation(58.0, 10.0), CONNECTED, FULL, 100.0)
    assert r.required is True
    assert r.verdict == RIDES_THROUGH


def test_a_deviation_beyond_the_table_does_not():
    """Below 57.5 Hz the table says a facility may ride through or trip."""
    r = grade_frequency(deviation(57.0, 1.0), CONNECTED, FULL, 100.0)
    assert r.verdict == NOT_REQUIRED


def test_a_deviation_held_past_its_band_does_not_require_ride_through():
    r = grade_frequency(deviation(58.0, 400.0, total=500.0), CONNECTED, FULL, 100.0)
    assert r.verdict == NOT_REQUIRED


def test_a_flat_run_is_an_error_not_a_pass():
    flat = Trace([0.0, 10.0, 20.0], [60.0, 60.0, 60.0])
    assert grade_frequency(flat, CONNECTED, FULL, 100.0).verdict == ERROR


def test_disconnecting_during_a_required_deviation_fails():
    off = Trace([0.0, 2.0, 20.0], [1.0, 0.0, 0.0])
    r = grade_frequency(deviation(58.0, 10.0), off, FULL, 100.0)
    assert r.verdict == TRIPS
    assert r.trip_driver == "stays connected"


def test_ceasing_consumption_fails_because_the_rule_says_shall():
    """2.6.4(5): the facility "shall continue to consume electric current"."""
    stopped = Trace([0.0, 1.0, 11.0, 20.0], [100.0, 0.0, 100.0, 100.0])
    r = grade_frequency(deviation(58.0, 10.0), CONNECTED, stopped, 100.0)
    assert r.verdict == TRIPS
    assert r.trip_driver == "keeps consuming"


def test_falling_outside_the_ten_percent_band_is_reported_and_not_scored():
    """2.6.4(5) says the facility "should" stay within 10% of its
    pre-disturbance level. Should, not shall, so a breach is reported
    without deciding the verdict."""
    dip = Trace([0.0, 1.0, 11.0, 20.0], [100.0, 80.0, 100.0, 100.0])
    r = grade_frequency(deviation(58.0, 10.0), CONNECTED, dip, 100.0)
    c = check(r, "holds power within band")
    assert c.passed is False
    assert c.counts is False
    assert r.verdict == RIDES_THROUGH


def test_staying_inside_the_ten_percent_band_passes():
    small = Trace([0.0, 1.0, 11.0, 20.0], [100.0, 95.0, 100.0, 100.0])
    r = grade_frequency(deviation(58.0, 10.0), CONNECTED, small, 100.0)
    assert check(r, "holds power within band").passed is True


# --- 2.6.4(6), the frequency transfer route ----------------------------

def test_the_frequency_transfer_route_is_declared_not_inferred():
    dip = Trace([0.0, 1.0, 11.0, 11.5, 20.0], [100.0, 20.0, 20.0, 95.0, 95.0])
    plain = grade_frequency(deviation(58.0, 10.0), CONNECTED, dip, 100.0)
    assert check(plain, "frequency transfer route") is None

    declared = grade_frequency(
        deviation(58.0, 10.0), CONNECTED, dip, 100.0, transfer_scheme=True
    )
    assert check(declared, "frequency transfer route") is not None


def test_the_frequency_transfer_route_allows_two_seconds():
    slow = Trace([0.0, 1.0, 11.0, 14.0, 20.0], [100.0, 20.0, 20.0, 95.0, 95.0])
    r = grade_frequency(
        deviation(58.0, 10.0), CONNECTED, slow, 100.0, transfer_scheme=True
    )
    c = check(r, "frequency transfer route")
    assert c.passed is False
    assert "2.0 s allowed" in c.detail

    quick = Trace([0.0, 1.0, 11.0, 12.0, 20.0], [100.0, 20.0, 20.0, 95.0, 95.0])
    r2 = grade_frequency(
        deviation(58.0, 10.0), CONNECTED, quick, 100.0, transfer_scheme=True
    )
    assert check(r2, "frequency transfer route").passed is True


# --- codes without a frequency requirement ------------------------------

def test_energinet_states_no_frequency_requirement_here():
    r = grade_frequency(deviation(58.0, 10.0), CONNECTED, FULL, 100.0, code=ENERGINET)
    assert r.verdict == ERROR
    assert "no frequency ride-through requirement" in r.checks[0].detail


def test_both_ercot_codes_carry_the_same_frequency_table():
    assert ERCOT.frequency is ERCOT_FREQUENCY
    assert ERCOT_2028.frequency is ERCOT_FREQUENCY


def test_the_envelope_message_uses_hertz_not_per_unit():
    r = grade_frequency(deviation(58.0, 10.0), CONNECTED, FULL, 100.0)
    assert "Hz" in r.checks[0].detail
    assert "pu" not in r.checks[0].detail


# --- out of scope is stated, not silent ---------------------------------

def test_the_package_says_what_it_does_not_grade():
    clauses = {c for c, _ in ERCOT.out_of_scope}
    assert "2.15(3)(c)(i)" in clauses
    assert "2.15(3)(e)(i)" in clauses
    assert "2.15(3)(f)" in clauses
    for _, reason in ERCOT.out_of_scope:
        assert len(reason) > 40, "every exclusion needs a reason"


@pytest.mark.parametrize("code", [ERCOT, ERCOT_2028])
def test_both_ercot_codes_declare_their_exclusions(code):
    assert len(code.out_of_scope) == 7
