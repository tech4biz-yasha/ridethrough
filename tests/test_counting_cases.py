"""The two counting cases in examples/ must keep giving the numbers they state.

Each case is one voltage event counted two ways against ERCOT Table A, and
the two ways disagree on whether ride-through is required. The cases are
quoted outside this repository, so the numbers are pinned here.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from ridethrough import ERCOT_VOLTAGE, excursions, ride_through_required

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "examples" / "counting_cases.py"


def load():
    spec = importlib.util.spec_from_file_location("counting_cases", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cases = load()


def seconds(rows, upper_edge):
    """The time counted against the band whose upper edge is given."""
    return next(spent for band, spent in rows if band.high == upper_edge)


def test_case_one_counted_band_by_band_requires_ride_through():
    rows = cases.time_in_each_band(cases.MULTI_BAND)
    assert seconds(rows, 0.50) == pytest.approx(0.2)
    assert seconds(rows, 0.90) == pytest.approx(1.9)
    assert seconds(rows, 0.80) == pytest.approx(0.0)
    assert seconds(rows, 0.35) == pytest.approx(0.0)
    assert ERCOT_VOLTAGE.minimum_time(0.45) == 0.25
    assert ERCOT_VOLTAGE.minimum_time(0.85) == 2.0
    assert cases.within(rows) is True


def test_case_one_counted_below_each_edge_does_not():
    rows = cases.time_below_each_edge(cases.MULTI_BAND)
    assert seconds(rows, 0.90) == pytest.approx(2.1)
    assert cases.within(rows) is False
    required, reason = ride_through_required(cases.MULTI_BAND, ERCOT_VOLTAGE)
    assert required is False
    assert "2.100 s below 0.90 pu" in reason
    assert "2.00 s allowed" in reason


def test_case_two_is_six_sags_inside_ninety_seconds():
    pieces = excursions(
        cases.SIX_SAGS, ERCOT_VOLTAGE.continuous_low, ERCOT_VOLTAGE.continuous_high
    )
    assert len(pieces) == 6
    for piece in pieces:
        assert piece.minimum() == 0.85
        assert piece.time_below(0.90) == pytest.approx(0.4)
    first_begins = pieces[0].times[0]
    last_ends = pieces[-1].times[-1]
    assert last_ends - first_begins == pytest.approx(75.4)
    assert last_ends - first_begins < cases.WINDOW_SECONDS == 90.0


def test_case_two_assessed_one_sag_at_a_time_requires_ride_through():
    rows = cases.longest_below_each_edge(cases.SIX_SAGS)
    assert seconds(rows, 0.90) == pytest.approx(0.4)
    assert cases.within(rows) is True
    required, reason = ride_through_required(cases.SIX_SAGS, ERCOT_VOLTAGE)
    assert required is True
    assert "6 separate excursions" in reason


def test_case_two_added_across_the_sags_does_not():
    rows = cases.time_below_each_edge(cases.SIX_SAGS)
    assert seconds(rows, 0.90) == pytest.approx(2.4)
    assert cases.within(rows) is False


def test_the_script_runs_and_prints_both_readings_of_both_cases():
    r = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert out.count("The facility must ride through.") == 2
    assert out.count("The facility is not required to ride through.") == 2
    for figure in ("0.200 s", "1.900 s", "2.100 s", "0.400 s", "2.400 s"):
        assert figure in out
    assert ERCOT_VOLTAGE.source in out
