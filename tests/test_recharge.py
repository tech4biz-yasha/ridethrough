"""Tests for refilling the energy stores between disturbances.

These exist because of a bug. Until 0.5.0 each stage drew only what the
load demanded, so a store that drained during a sag never refilled. A
facility therefore appeared to lose a little more of its store at every sag
and to collapse after a few, regardless of how much time passed in between.
Every single-sag result was unaffected, which is why 104 tests passed over
it: nothing measured what happened between two disturbances.
"""

import pytest

from ridethrough.archetypes import SERVER_PSU, UPS_DC_BUS, double_conversion_ups, no_ups
from ridethrough.facility import (
    dominion_july_2024,
    reclosing_sequence,
    repeated_sags,
    simulate,
)

RATED = 50e6


def test_the_ups_bus_returns_to_nominal_between_sags():
    traces = simulate(
        double_conversion_ups(RATED),
        repeated_sags(0.683, 0.075, count=6, interval_s=5.0),
        duration_s=40.0,
    )
    nominal = UPS_DC_BUS.nominal_dc_volts
    # Sampled well after each sag and well before the next.
    for t in (4.0, 9.0, 14.0, 19.0, 24.0):
        assert traces.ups_bus_volts.at(t) == pytest.approx(nominal, rel=1e-3)


def test_the_psu_store_returns_to_nominal_between_sags():
    traces = simulate(
        no_ups(RATED),
        repeated_sags(0.50, 0.010, count=4, interval_s=2.0),
        duration_s=12.0,
    )
    nominal = SERVER_PSU.nominal_dc_volts
    for t in (1.5, 3.5, 5.5):
        assert traces.psu_bus_volts.at(t) == pytest.approx(nominal, rel=1e-3)


def test_a_store_that_refills_does_not_accumulate_damage():
    """Six well-separated sags must leave a facility no worse off than one,
    which is the whole point of the fix."""
    one = simulate(
        double_conversion_ups(RATED),
        reclosing_sequence(0.683, 0.075, [0.5]),
        duration_s=40.0,
    )
    six = simulate(
        double_conversion_ups(RATED),
        repeated_sags(0.683, 0.075, count=6, interval_s=5.0),
        duration_s=40.0,
    )
    assert one.trip_driver is None
    assert six.trip_driver is None


def test_refill_is_bounded_by_the_current_limit():
    """The store cannot refill faster than the current limit allows, so a
    facility given no recovery time still runs out."""
    traces = simulate(
        double_conversion_ups(RATED),
        reclosing_sequence(0.50, 0.3, [0.5]),
        duration_s=5.0,
    )
    assert traces.trip_driver is not None


def test_refill_never_pushes_a_store_above_nominal():
    traces = simulate(
        double_conversion_ups(RATED),
        repeated_sags(0.683, 0.075, count=3, interval_s=5.0),
        duration_s=20.0,
    )
    assert max(traces.ups_bus_volts.values) <= UPS_DC_BUS.nominal_dc_volts + 1e-6
    assert max(traces.psu_bus_volts.values) <= SERVER_PSU.nominal_dc_volts + 1e-6


# --- the published reclosing pattern -----------------------------------

def test_the_dominion_pattern_has_six_sags_at_the_published_delays():
    """Six sags: the fault and its instantaneous reclose, then the same at
    the 20 second and 80 second reclosing delays."""
    profile = dominion_july_2024()
    inside = (0.52, 1.02, 20.52, 21.02, 80.52, 81.02)
    outside = (0.40, 0.60, 5.00, 50.00, 90.00)
    for t in inside:
        assert profile(t) == pytest.approx(0.683), f"expected a sag at {t}"
    for t in outside:
        assert profile(t) == pytest.approx(1.0), f"expected nominal at {t}"


def test_the_dominion_pattern_uses_the_published_magnitude_and_duration():
    profile = dominion_july_2024()
    assert profile(0.5) == pytest.approx(0.683)
    assert profile(0.5 + 0.074) == pytest.approx(0.683)
    assert profile(0.5 + 0.076) == pytest.approx(1.0)


def test_reclosing_sequence_rejects_an_empty_schedule():
    with pytest.raises(ValueError):
        reclosing_sequence(0.5, 0.1, [])


def test_reclosing_sequence_sorts_its_times():
    profile = reclosing_sequence(0.4, 0.05, [3.0, 1.0, 2.0])
    for t in (1.01, 2.01, 3.01):
        assert profile(t) == pytest.approx(0.4)


# --- the reclosing subcommand ------------------------------------------

def test_reclosing_subcommand_runs_every_archetype(capsys):
    from ridethrough.archetypes import ARCHETYPES
    from ridethrough.cli import main

    code = main(["reclosing"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    for key in ARCHETYPES:
        assert key in out
    assert "Modelled, not measured" in out
    assert "not reproduce" in out or "Nothing here reproduces" in out


def test_reclosing_at_published_values_does_not_drain_a_ups():
    """At 0.683 pu for 75 ms, stored energy is not the failure mechanism.
    A UPS-backed facility with a current limit under the ceiling rides the
    whole pattern through."""
    from ridethrough.grade import RIDES_THROUGH, grade

    traces = simulate(
        double_conversion_ups(RATED), dominion_july_2024(), duration_s=120.0
    )
    assert traces.trip_driver is None
    result = grade(
        traces.voltage,
        traces.connected,
        traces.active_power,
        traces.current,
        traces.pre_disturbance_power,
        traces.max_normal_current,
    )
    assert result.verdict == RIDES_THROUGH


def test_a_sag_counter_trips_inside_its_window_and_not_outside_it():
    """The published pattern puts four sags inside a minute and two more
    well outside it. A counter set at four trips on the fourth. A counter
    set at five never trips, because the last two fall outside the window.
    """
    from dataclasses import replace

    from ridethrough.archetypes import ups_with_sag_counter

    base = ups_with_sag_counter(RATED)
    profile = dominion_july_2024()

    four = simulate(replace(base, sag_count_trip=4), profile, duration_s=120.0)
    assert four.trip_driver is not None
    assert four.trip_time == pytest.approx(21.0, abs=2e-3)

    five = simulate(replace(base, sag_count_trip=5), profile, duration_s=120.0)
    assert five.trip_driver is None
