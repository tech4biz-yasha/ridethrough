"""Recorder files in, rule quantities out, each against a known answer."""

import contextlib
import io
import math
import os
import re
import struct
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ridethrough import recording as rec
from ridethrough.grade import Trace
from ridethrough.prc029 import PRC029_TABLE_1_WIND, PRC029_TABLE_2_OTHER

KV = 230.0
LINE_TO_NEUTRAL = KV / math.sqrt(3.0)
CYCLE = 1.0 / 60.0
VOLTS = ("VA", "VB", "VC")
AMPS = ("IA", "IB", "IC")


def made(**changes):
    settings = dict(sample_rate=3840.0, duration=1.0, nominal_frequency=60.0,
                    nominal_kv=KV, voltage_pu=[(0.0, 1.0)])
    settings.update(changes)
    return rec.synthetic_recording(**settings)


def low_high(record, basis=rec.PHASE_TO_NEUTRAL, **more):
    return rec.voltage_per_unit(record, channels=VOLTS, nominal_kv=KV,
                                basis=basis, **more)


def sequence(record):
    return rec.positive_sequence(*(rec.phasors(record, name) for name in VOLTS))


# ------------------------------------------------------------- fundamental RMS

def test_steady_voltage_reads_its_rms_on_every_phase():
    record = made()
    for name in VOLTS:
        trace = rec.rms(rec.phasors(record, name))
        assert trace.minimum() == pytest.approx(LINE_TO_NEUTRAL, rel=1e-9)
        assert trace.maximum() == pytest.approx(LINE_TO_NEUTRAL, rel=1e-9)


def test_first_value_comes_at_the_end_of_the_first_cycle():
    found = rec.phasors(made(), "VA")
    assert found.samples_per_cycle == 64
    assert found.times[0] == pytest.approx(63 / 3840.0)
    assert len(found.times) == 3841 - 63


@pytest.mark.parametrize("rate, hertz", [(10000.0, 60.0), (4000.0, 50.0),
                                         (1000.0, 60.0), (15360.0, 60.0)])
def test_rms_is_right_at_other_sample_rates_and_at_50_hertz(rate, hertz):
    record = made(sample_rate=rate, nominal_frequency=hertz, duration=0.5)
    low, high = low_high(record)
    assert low.minimum() == pytest.approx(1.0, abs=1e-9)
    assert high.maximum() == pytest.approx(1.0, abs=1e-9)


def test_a_dc_offset_does_not_change_the_fundamental():
    record = made()
    va = record.channel("VA")
    lifted = replace(va, values=tuple(v + 40.0 for v in va.values))
    record = replace(record, channels=(lifted, *record.channels[1:]))
    trace = rec.rms(rec.phasors(record, "VA"))
    assert trace.minimum() == pytest.approx(LINE_TO_NEUTRAL, rel=1e-9)
    assert trace.maximum() == pytest.approx(LINE_TO_NEUTRAL, rel=1e-9)


def test_a_fifth_harmonic_does_not_change_the_fundamental():
    record = made()
    va = record.channel("VA")
    fifth = tuple(v + 0.1 * LINE_TO_NEUTRAL * math.sqrt(2.0)
                  * math.cos(2.0 * math.pi * 300.0 * t)
                  for t, v in zip(record.times, va.values, strict=True))
    record = replace(record, channels=(replace(va, values=fifth),
                                       *record.channels[1:]))
    trace = rec.rms(rec.phasors(record, "VA"))
    assert trace.minimum() == pytest.approx(LINE_TO_NEUTRAL, rel=1e-9)
    assert trace.maximum() == pytest.approx(LINE_TO_NEUTRAL, rel=1e-9)


def test_a_fifth_harmonic_leaks_a_little_when_the_window_is_not_whole_cycles():
    record = made(sample_rate=10000.0, duration=0.5)
    va = record.channel("VA")
    fifth = tuple(v + 0.1 * LINE_TO_NEUTRAL * math.sqrt(2.0)
                  * math.cos(2.0 * math.pi * 300.0 * t + 0.7)
                  for t, v in zip(record.times, va.values, strict=True))
    record = replace(record, channels=(replace(va, values=fifth),
                                       *record.channels[1:]))
    trace = rec.rms(rec.phasors(record, "VA"))
    assert 0.0003 < 1.0 - trace.minimum() / LINE_TO_NEUTRAL < 0.0004
    assert 0.0003 < trace.maximum() / LINE_TO_NEUTRAL - 1.0 < 0.0004


def test_rms_stays_right_at_the_end_of_a_long_record():
    record = made(duration=60.0, sample_rate=1920.0)
    trace = rec.rms(rec.phasors(record, "VC"))
    assert trace.values[-1] == pytest.approx(LINE_TO_NEUTRAL, rel=1e-9)
    assert trace.minimum() == pytest.approx(LINE_TO_NEUTRAL, rel=1e-9)


def test_phase_to_phase_is_root_three_times_phase_to_neutral():
    record = made()
    a, b = rec.phasors(record, "VA"), rec.phasors(record, "VB")
    between = rec.rms(rec.phase_to_phase(a, b))
    assert between.minimum() == pytest.approx(KV, rel=1e-9)
    assert between.maximum() == pytest.approx(KV, rel=1e-9)


def test_positive_sequence_needs_the_phases_in_order():
    record = made()
    a, b, c = (rec.phasors(record, name) for name in VOLTS)
    right = rec.rms(rec.positive_sequence(a, b, c))
    wrong = rec.rms(rec.positive_sequence(a, c, b))
    assert right.minimum() == pytest.approx(LINE_TO_NEUTRAL, rel=1e-9)
    assert wrong.maximum() < 1e-6


def test_missing_samples_are_refused_and_named():
    record = made(duration=0.1)
    va = record.channel("VA")
    holed = replace(va, values=(rec.MISSING, *va.values[1:]))
    record = replace(record, channels=(holed, *record.channels[1:]))
    with pytest.raises(ValueError, match="VA has missing samples"):
        rec.phasors(record, "VA")


def test_too_few_samples_per_cycle_is_refused():
    with pytest.raises(ValueError, match="at least 8 samples per cycle"):
        rec.phasors(made(sample_rate=360.0), "VA")


# ----------------------------------------------- lowest and highest, per unit

def test_three_phase_sag_reads_its_depth():
    record = made(voltage_pu=[(0.0, 1.0), (0.3, 0.5), (0.5, 1.0)])
    low, high = low_high(record)
    assert low.minimum() == pytest.approx(0.5, abs=1e-9)
    assert low.at(0.4) == pytest.approx(0.5, abs=1e-9)
    assert high.at(0.4) == pytest.approx(0.5, abs=1e-9)
    assert low.at(0.9) == pytest.approx(1.0, abs=1e-9)


def test_single_phase_sag_on_each_basis():
    record = made(voltage_pu={"A": [(0.0, 1.0), (0.3, 0.5), (0.5, 1.0)],
                              "B": [(0.0, 1.0)], "C": [(0.0, 1.0)]})
    low, high = low_high(record)
    assert low.at(0.4) == pytest.approx(0.5, abs=1e-9)
    assert high.at(0.4) == pytest.approx(1.0, abs=1e-9)
    # A at 0.5 and B at 1.0, 120 degrees apart: |A - B| = sqrt(0.25 + 0.5 + 1).
    low, high = low_high(record, basis=rec.PHASE_TO_PHASE)
    assert low.at(0.4) == pytest.approx(math.sqrt(1.75) / math.sqrt(3.0), abs=1e-9)
    assert high.at(0.4) == pytest.approx(1.0, abs=1e-9)


def test_phase_to_phase_channels_go_through_the_building_blocks():
    record = made(voltage_pu={"A": [(0.0, 1.0), (0.3, 0.5), (0.5, 1.0)],
                              "B": [(0.0, 1.0)], "C": [(0.0, 1.0)]})
    va, vb, vc = (record.channel(name).values for name in VOLTS)
    between = tuple(
        rec.Channel(name, tuple(p - q for p, q in zip(first, second, strict=True)),
                    "kV")
        for name, first, second in (("VAB", va, vb), ("VBC", vb, vc),
                                    ("VCA", vc, va)))
    record = replace(record, channels=between)
    traces = [rec.per_unit(rec.rms(rec.phasors(record, ch.name)), KV)
              for ch in between]
    low, high = rec.lowest(traces), rec.highest(traces)
    assert low.at(0.4) == pytest.approx(math.sqrt(1.75) / math.sqrt(3.0), abs=1e-9)
    assert high.at(0.4) == pytest.approx(1.0, abs=1e-9)
    assert low.at(0.9) == pytest.approx(1.0, abs=1e-9)


def test_the_basis_has_to_be_stated():
    with pytest.raises(TypeError):
        rec.voltage_per_unit(made(), channels=VOLTS, nominal_kv=KV)
    with pytest.raises(ValueError, match="basis must be"):
        low_high(made(duration=0.1), basis="line")


def test_voltage_per_unit_wants_three_voltage_channels():
    record = made(duration=0.1)
    with pytest.raises(ValueError, match="three phase-to-neutral"):
        rec.voltage_per_unit(record, channels=("VA", "VB"), nominal_kv=KV,
                             basis=rec.PHASE_TO_NEUTRAL)
    with pytest.raises(ValueError, match="voltage channel needs one of"):
        rec.voltage_per_unit(record, channels=AMPS, nominal_kv=KV,
                             basis=rec.PHASE_TO_NEUTRAL)


def test_channels_in_volts_give_the_same_per_unit():
    record = made(duration=0.2)
    in_volts = tuple(
        replace(ch, values=tuple(v * 1000.0 for v in ch.values), unit="V")
        if ch.name in VOLTS else ch for ch in record.channels)
    low, high = low_high(replace(record, channels=in_volts))
    assert low.minimum() == pytest.approx(1.0, abs=1e-9)
    assert high.maximum() == pytest.approx(1.0, abs=1e-9)


def test_a_deep_sag_reads_long_by_less_than_one_cycle():
    record = made(voltage_pu=[(0.0, 1.0), (0.3, 0.5), (0.5, 1.0)])
    low, _ = low_high(record)
    assert 0.2 < low.time_below(0.90) < 0.2 + CYCLE
    assert low.time_below(0.90) == pytest.approx(0.2125, abs=1e-6)


def test_a_shallow_sag_reads_short_by_less_than_one_cycle():
    record = made(voltage_pu=[(0.0, 1.0), (0.3, 0.89), (0.5, 1.0)])
    low, _ = low_high(record)
    assert 0.2 - CYCLE < low.time_below(0.90) < 0.2
    assert low.time_below(0.90) == pytest.approx(0.191146, abs=1e-6)


def test_lowest_and_highest_want_one_time_base():
    one = Trace([0.0, 1.0], [1.0, 0.8])
    other = Trace([0.0, 2.0], [0.9, 0.9])
    assert rec.lowest([one, Trace([0.0, 1.0], [0.9, 0.9])]).values == [0.9, 0.8]
    assert rec.highest([one, Trace([0.0, 1.0], [0.9, 0.9])]).values == [1.0, 0.9]
    with pytest.raises(ValueError, match="same time base"):
        rec.lowest([one, other])
    with pytest.raises(ValueError, match="at least one"):
        rec.highest([])
    with pytest.raises(ValueError, match="base must be positive"):
        rec.per_unit(one, 0.0)


# ------------------------------------------ away from nominal frequency

@pytest.mark.parametrize("hertz, low_swing, high_swing", [
    (59.9, -0.00084, 0.00083), (59.5, -0.00430, 0.00408),
    (58.8, -0.01077, 0.00945), (57.0, -0.02968, 0.02147),
    (60.5, -0.00427, 0.00404), (61.8, -0.01626, 0.01330),
])
def test_per_phase_reading_swings_when_the_system_is_off_nominal(
        hertz, low_swing, high_swing):
    record = made(duration=2.0, frequency_hz=[(0.0, hertz)])
    low, high = low_high(record)
    assert low.minimum() - 1.0 == pytest.approx(low_swing, abs=2e-5)
    assert high.maximum() - 1.0 == pytest.approx(high_swing, abs=2e-5)


def test_the_swing_comes_twice_a_cycle():
    record = made(duration=2.0, frequency_hz=[(0.0, 59.5)])
    trace = rec.rms(rec.phasors(record, "VA"))
    second = [v for t, v in zip(trace.times, trace.values, strict=True)
              if 0.5 <= t < 1.5]
    middle = sum(second) / len(second)
    rises = sum(1 for a, b in zip(second, second[1:], strict=False)
                if a <= middle < b)
    assert rises == 119


def test_fitting_at_the_system_frequency_removes_the_swing():
    record = made(duration=2.0, frequency_hz=[(0.0, 59.5)])
    low, high = low_high(record, at_frequency=59.5)
    assert low.minimum() == pytest.approx(1.0, abs=1e-9)
    assert high.maximum() == pytest.approx(1.0, abs=1e-9)
    assert rec.phasors(record, "VA", at_frequency=59.5).frequency == 59.5


def test_the_positive_sequence_does_not_swing_on_balanced_voltages():
    record = made(duration=2.0, frequency_hz=[(0.0, 59.5)])
    a, b, c = (rec.phasors(record, name) for name in VOLTS)
    steady = rec.rms(rec.positive_sequence(a, b, c))
    assert steady.minimum() / LINE_TO_NEUTRAL == pytest.approx(0.99989, abs=1e-5)
    assert steady.maximum() - steady.minimum() < 1e-9
    together = rec.frequency(rec.positive_sequence(a, b, c), cycles=6)
    assert together.minimum() == pytest.approx(59.5, abs=1e-6)
    assert together.maximum() == pytest.approx(59.5, abs=1e-6)
    alone = rec.frequency(a, cycles=6)
    assert alone.minimum() == pytest.approx(59.496, abs=5e-4)
    assert alone.maximum() == pytest.approx(59.504, abs=5e-4)


# ------------------------------------------------- frequency, rate, angle

def test_frequency_at_nominal():
    trace = rec.frequency(sequence(made()), cycles=6)
    assert trace.minimum() == pytest.approx(60.0, abs=1e-6)
    assert trace.maximum() == pytest.approx(60.0, abs=1e-6)
    assert trace.times[0] == pytest.approx((63 + 6 * 64) / 3840.0)


@pytest.mark.parametrize("hertz", [57.0, 58.8, 59.5, 60.3, 61.8])
@pytest.mark.parametrize("cycles", [3, 6])
def test_frequency_away_from_nominal(hertz, cycles):
    record = made(frequency_hz=[(0.0, hertz)])
    trace = rec.frequency(sequence(record), cycles=cycles)
    assert trace.minimum() == pytest.approx(hertz, abs=1e-6)
    assert trace.maximum() == pytest.approx(hertz, abs=1e-6)


def test_frequency_follows_a_step():
    record = made(frequency_hz=[(0.0, 60.0), (0.5, 59.0)])
    trace = rec.frequency(sequence(record), cycles=6)
    assert trace.at(0.45) == pytest.approx(60.0, abs=1e-6)
    assert trace.at(0.9) == pytest.approx(59.0, abs=1e-6)


def test_frequency_wants_whole_cycles():
    with pytest.raises(ValueError, match="at least 1"):
        rec.frequency(sequence(made(duration=0.2)), cycles=0)


def test_a_record_too_short_for_the_measurement_says_so():
    short = made(duration=0.05)
    with pytest.raises(ValueError, match="too short to give frequency over 6"):
        rec.frequency(sequence(short), cycles=6)
    with pytest.raises(ValueError, match="too short to give a rate of change"):
        rec.rate_of_change(rec.frequency(sequence(short), cycles=1), period=0.1)
    with pytest.raises(ValueError, match="shorter than one cycle"):
        rec.phasors(made(duration=0.01), "VA")
    with pytest.raises(ValueError, match="too short to give an RMS trace"):
        rec.rms(rec.phasors(made(duration=63 / 3840.0), "VA"))


def test_rate_of_change_on_a_ramp():
    ramp = [(0.0, 60.0)] + [(0.5 + i / 3840.0, 60.0 - 2.0 * i / 3840.0)
                            for i in range(1, 3841)]
    record = made(duration=2.0, frequency_hz=ramp)
    trace = rec.frequency(sequence(record), cycles=6)
    rate = rec.rate_of_change(trace, period=0.1)
    inside = [v for t, v in zip(rate.times, rate.values, strict=True)
              if 0.8 <= t <= 1.4]
    assert min(inside) == pytest.approx(-2.0, abs=1e-4)
    assert max(inside) == pytest.approx(-2.0, abs=1e-4)
    assert rate.at(0.4) == pytest.approx(0.0, abs=1e-6)


def test_rate_of_change_on_a_plain_trace():
    trace = Trace([0.0, 0.1, 0.2, 0.3], [60.0, 59.8, 59.6, 59.6])
    rate = rec.rate_of_change(trace, period=0.1)
    assert rate.times == [0.1, 0.2, 0.3]
    assert rate.values == pytest.approx([-2.0, -2.0, 0.0])
    with pytest.raises(ValueError, match="period must be positive"):
        rec.rate_of_change(trace, period=0.0)


@pytest.mark.parametrize("hertz", [60.0, 59.8])
@pytest.mark.parametrize("period", [CYCLE, 2 * CYCLE, 0.05])
def test_phase_angle_jump_reads_its_size(hertz, period):
    record = made(frequency_hz=[(0.0, hertz)], phase_jump=(0.5, 25.0))
    angle = rec.angle_degrees(sequence(record))
    jump = rec.angle_jump(angle, period=period)
    assert jump.maximum() == pytest.approx(25.0, abs=1e-6)
    assert jump.minimum() == pytest.approx(-25.0, abs=1e-6)
    assert jump.at(0.4) == pytest.approx(0.0, abs=1e-6)


def test_a_period_shorter_than_a_cycle_reads_a_jump_short():
    record = made(phase_jump=(0.5, 25.0))
    angle = rec.angle_degrees(sequence(record))
    assert rec.angle_jump(angle, period=CYCLE / 2).maximum() == pytest.approx(
        12.5, abs=1e-6)
    with pytest.raises(ValueError, match="period must be positive"):
        rec.angle_jump(angle, period=0.0)


def test_a_phase_jump_also_shows_as_a_frequency_blip():
    record = made(phase_jump=(0.5, 25.0))
    trace = rec.frequency(sequence(record), cycles=6)
    # 25 degrees turned within six cycles: 25 / 360 / 0.1 s.
    assert trace.maximum() == pytest.approx(60.0 + 25.0 / 360.0 / 0.1, abs=1e-6)


def test_angle_is_unwrapped():
    record = made(frequency_hz=[(0.0, 61.0)])
    angle = rec.angle_degrees(sequence(record))
    steps = [b - a for a, b in zip(angle.values, angle.values[1:], strict=False)]
    assert max(abs(s) for s in steps) < 1.0
    assert angle.values[-1] - angle.values[0] == pytest.approx(
        360.0 * (angle.times[-1] - angle.times[0]), abs=1e-6)


# ------------------------------------------------------------------ real power

def test_real_power_balanced():
    record = made(megawatts=[(0.0, 100.0)])
    power = rec.real_power(record, voltages=VOLTS, currents=AMPS)
    assert power.minimum() == pytest.approx(100.0, abs=1e-9)
    assert power.maximum() == pytest.approx(100.0, abs=1e-9)
    assert power.times[0] == pytest.approx(63 / 3840.0)


def test_real_power_sign_and_step():
    record = made(megawatts=[(0.0, 100.0), (0.5, 40.0)])
    power = rec.real_power(record, voltages=VOLTS, currents=AMPS)
    assert power.at(0.45) == pytest.approx(100.0, abs=1e-9)
    assert power.at(0.5 + CYCLE) == pytest.approx(40.0, abs=1e-9)
    back = rec.real_power(record, voltages=VOLTS, currents=AMPS, sign=-1.0)
    assert back.at(0.45) == pytest.approx(-100.0, abs=1e-9)


def test_real_power_holds_through_a_sag_when_current_rises():
    record = made(voltage_pu=[(0.0, 1.0), (0.3, 0.5), (0.5, 1.0)],
                  megawatts=[(0.0, 100.0)])
    power = rec.real_power(record, voltages=VOLTS, currents=AMPS)
    assert power.at(0.4) == pytest.approx(100.0, abs=1e-9)


def test_real_power_at_a_sample_rate_that_is_not_whole_cycles():
    record = made(sample_rate=10000.0, megawatts=[(0.0, 100.0)], duration=0.5)
    power = rec.real_power(record, voltages=VOLTS, currents=AMPS)
    assert power.minimum() == pytest.approx(100.0, abs=1e-9)
    assert power.maximum() == pytest.approx(100.0, abs=1e-9)


@pytest.mark.parametrize("rate, lowest, highest", [
    (3840.0, 83.3333, 83.3333), (10000.0, 83.3001, 83.3666)])
def test_real_power_with_one_phase_at_half(rate, lowest, highest):
    record = made(sample_rate=rate, megawatts=[(0.0, 100.0)],
                  voltage_pu={"A": [(0.0, 1.0), (0.3, 0.5), (0.7, 1.0)],
                              "B": [(0.0, 1.0)], "C": [(0.0, 1.0)]})
    # The synthetic current rises to hold power, so halve it again in the sag.
    ia = record.channel("IA")
    held = tuple(v * (0.5 if 0.3 - 1e-12 <= t < 0.7 - 1e-12 else 1.0)
                 for t, v in zip(record.times, ia.values, strict=True))
    channels = tuple(replace(ch, values=held) if ch.name == "IA" else ch
                     for ch in record.channels)
    power = rec.real_power(replace(record, channels=channels), voltages=VOLTS,
                           currents=AMPS)
    inside = [v for t, v in zip(power.times, power.values, strict=True)
              if 0.4 <= t <= 0.6]
    # True power is 100 * (1/6 + 2/3) = 83.3333 MW.
    assert min(inside) == pytest.approx(lowest, abs=1e-4)
    assert max(inside) == pytest.approx(highest, abs=1e-4)


def test_real_power_checks_its_channels():
    record = made(duration=0.1)
    ia = record.channel("IA")
    holed = tuple(replace(ch, values=(rec.MISSING, *ia.values[1:]))
                  if ch.name == "IA" else ch for ch in record.channels)
    with pytest.raises(ValueError, match="has missing samples"):
        rec.real_power(replace(record, channels=holed), voltages=VOLTS,
                       currents=AMPS)
    with pytest.raises(ValueError, match="one current channel for each"):
        rec.real_power(record, voltages=VOLTS, currents=("IA",))
    with pytest.raises(ValueError, match="current channel needs one of"):
        rec.real_power(record, voltages=VOLTS, currents=VOLTS)
    with pytest.raises(ValueError, match="voltage channel needs one of"):
        rec.real_power(record, voltages=AMPS, currents=AMPS)
    with pytest.raises(KeyError, match="no channel 'IN'"):
        rec.real_power(record, voltages=VOLTS, currents=("IA", "IB", "IN"))


# ------------------------------------------------------- deviations and window

def flat(values, step=1.0):
    return Trace([i * step for i in range(len(values))], list(values))


def test_one_deviation_per_trip_out_of_the_continuous_region():
    low = flat([1.0, 0.5, 0.5, 1.0, 1.0, 0.8, 1.0, 1.0])
    high = flat([1.0] * 8)
    assert rec.deviations(low, high, PRC029_TABLE_2_OTHER) == [(1.0, 3.0), (5.0, 6.0)]


def test_high_voltage_counts_as_a_deviation_too():
    low = flat([1.0] * 5)
    high = flat([1.0, 1.15, 1.0, 1.08, 1.0])
    assert rec.deviations(low, high, PRC029_TABLE_2_OTHER) == [(1.0, 2.0)]


def test_the_two_tables_differ_at_exactly_1_10():
    low = flat([1.0, 1.0, 1.0])
    high = flat([1.0, 1.10, 1.0])
    assert rec.deviations(low, high, PRC029_TABLE_1_WIND) == [(1.0, 2.0)]
    assert rec.deviations(low, high, PRC029_TABLE_2_OTHER) == []


def test_a_deviation_still_open_ends_with_the_record():
    low = flat([1.0, 0.5, 0.5])
    assert rec.deviations(low, flat([1.0] * 3), PRC029_TABLE_2_OTHER) == [(1.0, 2.0)]


def test_deviations_want_one_time_base():
    with pytest.raises(ValueError, match="same time base"):
        rec.deviations(flat([1.0, 1.0]), flat([1.0, 1.0], step=2.0),
                       PRC029_TABLE_2_OTHER)


def test_event_window():
    low = flat([1.0, 1.0, 0.5, 1.0, 0.6, 1.0, 1.0, 1.0])
    high = flat([1.0] * 8)
    table = PRC029_TABLE_2_OTHER
    assert rec.event_window(low, high, table) == (2.0, 5.0)
    assert rec.event_window(low, high, table, before=1.5, after=1.0) == (0.5, 6.0)
    assert rec.event_window(low, high, table, before=9.0, after=9.0) == (0.0, 7.0)
    assert rec.event_window(high, high, table) is None


def test_a_recorded_sag_is_one_deviation_within_a_cycle_of_the_truth():
    record = made(voltage_pu=[(0.0, 1.0), (0.3, 0.5), (0.5, 1.0)])
    low, high = low_high(record)
    found = rec.deviations(low, high, PRC029_TABLE_2_OTHER)
    assert len(found) == 1
    began, ended = found[0]
    assert 0.3 < began < 0.3 + CYCLE
    assert 0.5 < ended < 0.5 + CYCLE


# ------------------------------------------------------------------- COMTRADE

CFG_1999 = """SUB_A,DFR_1,1999
4,2A,2D
1,VA,A,,kV,0.5,1.0,0,-32767,32767,400,2,S
2,IA,A,,A,2.0,0,0,-32767,32767,1200,5,P
1,TRIP,,,0
2,BLOCK,,,1
60
1
1000,4
09/03/2026,14:05:06.250000
09/03/2026,14:05:06.252000
ASCII
1
"""
DAT_1999 = ("1,0,100,-20,0,1\n2,1000,200,-10,1,1\n3,2000,-300,0,1,0\n"
            "4,3000,99999,10,0,0\n")


def pair(folder, cfg, dat, stem="event", suffix=".dat", encoding="utf-8"):
    path = folder / f"{stem}.cfg"
    path.write_text(cfg, encoding=encoding)
    other = folder / f"{stem}{suffix}"
    if isinstance(dat, bytes):
        other.write_bytes(dat)
    else:
        other.write_text(dat, encoding=encoding)
    return path


def test_1999_text_file(tmp_path):
    got = rec.read_comtrade(pair(tmp_path, CFG_1999, DAT_1999))
    assert (got.name, got.device) == ("SUB_A", "DFR_1")
    assert got.names == ("VA", "IA")
    assert got.times == (0.0, 0.001, 0.002, 0.003)
    assert got.sample_rate == 1000.0
    assert got.nominal_frequency == 60.0
    assert got.duration == 0.003
    va = got.channel("VA")
    assert (va.unit, va.phase) == ("kV", "A")
    # (0.5 * raw + 1.0) on the secondary side, times 400 / 2 to the primary.
    assert va.values[:3] == pytest.approx([10200.0, 20200.0, -29800.0])
    assert math.isnan(va.values[3])
    assert got.channel("IA").values == pytest.approx([-40.0, -20.0, 0.0, 20.0])
    assert got.start == datetime(2026, 3, 9, 14, 5, 6, 250000)
    assert got.trigger == datetime(2026, 3, 9, 14, 5, 6, 252000)
    assert got.trigger_time == pytest.approx(0.002)
    assert got.utc_offset is None
    assert [(s.name, s.values) for s in got.status] == [
        ("TRIP", (0, 1, 1, 0)), ("BLOCK", (1, 1, 0, 0))]


def test_secondary_values_on_request(tmp_path):
    got = rec.read_comtrade(pair(tmp_path, CFG_1999, DAT_1999), primary=False)
    assert got.channel("VA").values[:3] == pytest.approx([51.0, 101.0, -149.0])
    assert got.channel("IA").values == pytest.approx(
        [v * 5.0 / 1200.0 for v in (-40.0, -20.0, 0.0, 20.0)])


CFG_1991 = """SUB_A,7
3,2A,1D
1,VA,A,,kV,0.01,0,0,-2048,2047
2,IA,A,,A,2,0,0,-2048,2047
1,TRIP,0
60
1
1000,3
03/09/{year},14:05:06.250000
03/09/{year},14:05:06.251000
ASCII
"""
DAT_1991 = "1,0,100,-20,0\n2,1000,99999,,1\n3,2000,-300,5,1\n"


@pytest.mark.parametrize("written, year", [("26", 2026), ("95", 1995)])
def test_1991_text_file(tmp_path, written, year):
    got = rec.read_comtrade(pair(tmp_path, CFG_1991.format(year=written), DAT_1991))
    assert (got.name, got.device) == ("SUB_A", "7")
    # The 1991 layout writes the month first.
    assert got.start == datetime(year, 3, 9, 14, 5, 6, 250000)
    assert got.trigger_time == pytest.approx(0.001)
    # 99999 is a value here, and an empty field is a missing one.
    assert got.channel("VA").values == pytest.approx([1.0, 999.99, -3.0])
    ia = got.channel("IA").values
    assert ia[0] == -40.0 and math.isnan(ia[1]) and ia[2] == 10.0
    assert got.status[0].values == (0, 1, 1)


CFG_2013 = """SUB_A,DFR_1,2013
2,2A,0D
1,VA,A,,kV,1,0,0,-32767,32767,1,1,P
2,VB,B,,kV,1,0,0,-32767,32767,1,1,P
60
0
0,3
09/03/2026,14:05:06.{fraction}
09/03/2026,14:05:06.{fraction}
ASCII
2
{code},{code}
0,0
"""


@pytest.mark.parametrize("fraction, stamps", [
    ("250000", (0, 500, 1000)), ("250000000", (0, 500000, 1000000))])
def test_2013_text_file_timed_by_its_stamps(tmp_path, fraction, stamps):
    dat = "".join(f"{i + 1},{s},{5 + i},{8 + i}\n" for i, s in enumerate(stamps))
    cfg = CFG_2013.format(fraction=fraction, code="-5h30")
    got = rec.read_comtrade(pair(tmp_path, cfg, dat))
    # Stamps count microseconds, or nanoseconds when the start time is
    # written to nine places, and the multiplier here is 2.
    assert got.times == pytest.approx((0.0, 0.001, 0.002))
    assert got.sample_rate == pytest.approx(1000.0)
    assert got.start == datetime(2026, 3, 9, 14, 5, 6, 250000)
    assert got.utc_offset == timedelta(hours=-5, minutes=-30)
    assert got.channel("VB").values == (8.0, 9.0, 10.0)


@pytest.mark.parametrize("code, offset", [
    ("0", timedelta(0)), ("+10", timedelta(hours=10)),
    ("5h30", timedelta(hours=5, minutes=30)), ("x", None), ("", None),
    ("25", None)])
def test_2013_time_codes(tmp_path, code, offset):
    cfg = CFG_2013.format(fraction="250000", code=code)
    got = rec.read_comtrade(pair(tmp_path, cfg, "1,0,5,8\n2,500,6,9\n3,1000,7,10\n"))
    assert got.utc_offset == offset


def test_stamps_are_needed_when_no_rate_is_stated(tmp_path):
    cfg = CFG_2013.format(fraction="250000", code="0")
    with pytest.raises(ValueError, match="missing time stamp"):
        rec.read_comtrade(pair(tmp_path, cfg, "1,0,5,8\n2,,6,9\n3,1000,7,10\n"))


CFG_BINARY = """SUB_A,DFR_1,{revision}
20,2A,18D
1,VA,A,,kV,0.5,0,0,-32767,32767,1,1,P
2,IA,A,,A,2,1,0,-32767,32767,1,1,P
{status}60
1
2000,3
09/03/2026,14:05:06.250000
09/03/2026,14:05:06.250000
{kind}
1
"""
STATUS_18 = "".join(f"{k},S{k},,,0\n" for k in range(1, 19))


def test_binary_file(tmp_path):
    rows = [(1, 0, 100, -20, 0b101, 0b10), (2, 500, -32768, 7, 0, 0),
            (3, 1000, -300, 5, 0x8000, 0b01)]
    dat = b"".join(struct.pack("<IIhhHH", *row) for row in rows)
    cfg = CFG_BINARY.format(revision=1999, status=STATUS_18, kind="BINARY")
    got = rec.read_comtrade(pair(tmp_path, cfg, dat))
    assert got.times == (0.0, 0.0005, 0.001)
    va = got.channel("VA").values
    assert va[0] == 50.0 and math.isnan(va[1]) and va[2] == -150.0
    assert got.channel("IA").values == (-39.0, 15.0, 11.0)
    held = {s.name: s.values for s in got.status}
    assert len(held) == 18
    assert held["S1"] == (1, 0, 0) and held["S3"] == (1, 0, 0)
    assert held["S2"] == (0, 0, 0) and held["S16"] == (0, 0, 1)
    assert held["S17"] == (0, 0, 1) and held["S18"] == (1, 0, 0)


def test_binary_file_with_a_1991_configuration_keeps_every_value(tmp_path):
    cfg = "SUB_A,7\n1,1A,0D\n1,VA,A,,kV,1,0,0,-2048,2047\n60\n1\n2000,3\n"
    cfg += "03/09/26,14:05:06.250000\n03/09/26,14:05:06.250000\nBINARY\n"
    dat = b"".join(struct.pack("<IIh", i + 1, 500 * i, x)
                   for i, x in enumerate((-1, -32768, 7)))
    got = rec.read_comtrade(pair(tmp_path, cfg, dat))
    assert got.channel("VA").values == (-1.0, -32768.0, 7.0)


@pytest.mark.parametrize("kind, code, values, missing", [
    ("BINARY32", "i", (100000, -2147483648, -300000), -2147483648),
    ("FLOAT32", "f", (1.5, -3.4028234663852886e38, -2.25), None)])
def test_2013_wide_binary_files(tmp_path, kind, code, values, missing):
    cfg = CFG_BINARY.format(revision=2013, status="", kind=kind)
    cfg = cfg.replace("20,2A,18D", "2,2A,0D")
    dat = b"".join(struct.pack("<II" + code * 2, i + 1, 500 * i, x, 4)
                   for i, x in enumerate(values))
    got = rec.read_comtrade(pair(tmp_path, cfg, dat))
    va = got.channel("VA").values
    assert va[0] == pytest.approx(0.5 * values[0])
    assert math.isnan(va[1])
    assert va[2] == pytest.approx(0.5 * values[2])
    assert got.channel("IA").values == (9.0, 9.0, 9.0)


def test_more_than_one_sample_rate_is_read_but_not_measured(tmp_path):
    cfg = CFG_1999.replace("4,2A,2D", "2,2A,0D").replace(
        "1,TRIP,,,0\n2,BLOCK,,,1\n", "").replace("1\n1000,4", "2\n1000,3\n500,5")
    dat = "".join(f"{i},0,{i},{i}\n" for i in range(1, 6))
    got = rec.read_comtrade(pair(tmp_path, cfg, dat))
    assert got.times == pytest.approx((0.0, 0.001, 0.002, 0.004, 0.006))
    assert got.sample_rate is None
    with pytest.raises(ValueError, match="one sample rate"):
        rec.phasors(got, "VA")


def test_fewer_samples_than_stated_gives_a_warning(tmp_path):
    cfg = CFG_1999.replace("1000,4", "1000,9")
    with pytest.warns(UserWarning, match="holds 4 samples; the .cfg states 9"):
        got = rec.read_comtrade(pair(tmp_path, cfg, DAT_1999))
    assert len(got.times) == 4


def test_rows_past_the_stated_count_are_left_out(tmp_path):
    cfg = CFG_1999.replace("1000,4", "1000,3")
    assert len(rec.read_comtrade(pair(tmp_path, cfg, DAT_1999)).times) == 3


def test_a_row_with_the_wrong_number_of_fields_is_named(tmp_path):
    dat = DAT_1999.replace("2,1000,200,-10,1,1\n", "2,1000,200,-10,1\n")
    with pytest.raises(ValueError, match="line 2 has 5 fields; the .cfg calls for 6"):
        rec.read_comtrade(pair(tmp_path, CFG_1999, dat))


def test_a_cut_off_configuration_is_refused(tmp_path):
    cut = "\n".join(CFG_1999.splitlines()[:7]) + "\n"
    with pytest.raises(ValueError, match="ends before the COMTRADE layout"):
        rec.read_comtrade(pair(tmp_path, cut, DAT_1999))


def test_a_channel_with_no_ratio_is_left_as_written(tmp_path):
    cfg = CFG_1999.replace("400,2,S", ",,").replace("2.0,0,0,-32767", "2.0,,0,-32767")
    got = rec.read_comtrade(pair(tmp_path, cfg, DAT_1999))
    assert got.channel("VA").values[:3] == pytest.approx([51.0, 101.0, -149.0])
    assert got.channel("IA").values == pytest.approx([-40.0, -20.0, 0.0, 20.0])


def test_a_channel_with_no_multiplier_is_refused(tmp_path):
    cfg = CFG_1999.replace("kV,0.5,1.0", "kV,,1.0")
    with pytest.raises(ValueError, match="channel VA has no multiplier"):
        rec.read_comtrade(pair(tmp_path, cfg, DAT_1999))


def test_unknown_data_type_is_refused(tmp_path):
    with pytest.raises(ValueError, match="unsupported COMTRADE data file type"):
        rec.read_comtrade(pair(tmp_path, CFG_1999.replace("ASCII", "ZIP"), DAT_1999))


def test_the_dat_file_is_found_or_reported(tmp_path):
    got = rec.read_comtrade(pair(tmp_path, CFG_1999, DAT_1999, suffix=".DAT"))
    assert len(got.times) == 4
    alone = tmp_path / "alone.cfg"
    alone.write_text(CFG_1999, encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="no .dat file beside"):
        rec.read_comtrade(alone)
    named = tmp_path / "elsewhere.txt"
    named.write_text(DAT_1999, encoding="utf-8")
    assert len(rec.read_comtrade(alone, named).times) == 4


def test_latin_1_text_and_an_end_of_file_mark(tmp_path):
    cfg = CFG_1999.replace("SUB_A", "Subestação") + "\x1a"
    got = rec.read_comtrade(pair(tmp_path, cfg, DAT_1999 + "\x1a",
                                 encoding="latin-1"))
    assert got.name == "Subestação"
    assert len(got.times) == 4


def test_an_end_of_file_mark_straight_after_the_last_character(tmp_path):
    cfg = CFG_1991.format(year="26").rstrip("\n") + "\x1a"
    got = rec.read_comtrade(pair(tmp_path, cfg, DAT_1991.rstrip("\n") + "\x1a"))
    assert got.status[0].values == (0, 1, 1)


def test_a_file_with_no_line_frequency_needs_one_given(tmp_path):
    cfg = CFG_1999.replace("\n60\n", "\n\n")
    path = pair(tmp_path, cfg, DAT_1999)
    with pytest.raises(ValueError, match="states no line frequency"):
        rec.read_comtrade(path)
    assert rec.read_comtrade(path, nominal_frequency=50.0).nominal_frequency == 50.0


def event():
    record = made(sample_rate=1920.0, duration=0.25, megawatts=[(0.0, 80.0)],
                  voltage_pu=[(0.0, 1.0), (0.1, 0.4), (0.18, 1.0)],
                  start=datetime(2026, 3, 9, 14, 5, 6, 123456), name="PLANT")
    flags = tuple(1 if 0.1 <= t < 0.18 else 0 for t in record.times)
    return replace(record, device="DFR7",
                   trigger=datetime(2026, 3, 9, 14, 5, 6, 223456),
                   status=(rec.Status("TRIP", flags),
                           rec.Status("READY", tuple(1 - f for f in flags))))


@pytest.mark.parametrize("revision", [1991, 1999, 2013])
@pytest.mark.parametrize("binary", [False, True])
def test_what_is_written_reads_back(tmp_path, revision, binary):
    record = event()
    path = tmp_path / "out.cfg"
    rec.write_comtrade(record, path, revision=revision, binary=binary)
    back = rec.read_comtrade(path)
    assert (back.name, back.device) == ("PLANT", "DFR7")
    assert back.times == record.times
    assert back.sample_rate == record.sample_rate
    assert (back.start, back.trigger) == (record.start, record.trigger)
    assert back.status == record.status
    for wrote, read in zip(record.channels, back.channels, strict=True):
        assert (read.name, read.unit, read.phase) == (
            wrote.name, wrote.unit, wrote.phase)
        step = max(abs(v) for v in wrote.values) / 32767.0
        worst = max(abs(a - b) for a, b in zip(wrote.values, read.values,
                                               strict=True))
        assert worst <= step / 2.0 + 1e-12
    low, _ = low_high(back)
    assert low.at(0.15) == pytest.approx(0.4, abs=1e-4)
    power = rec.real_power(back, voltages=VOLTS, currents=AMPS)
    assert power.at(0.15) == pytest.approx(80.0, abs=0.01)


@pytest.mark.parametrize("offset", [timedelta(hours=5, minutes=30), timedelta(0),
                                    timedelta(hours=-6), None])
def test_the_utc_offset_is_written_in_the_2013_layout(tmp_path, offset):
    record = replace(event(), utc_offset=offset)
    rec.write_comtrade(record, tmp_path / "out.cfg", revision=2013)
    assert rec.read_comtrade(tmp_path / "out.cfg").utc_offset == offset


def test_writing_refuses_what_it_cannot_write(tmp_path):
    record = event()
    path = tmp_path / "out.cfg"
    with pytest.raises(ValueError, match="1991, 1999 or 2013"):
        rec.write_comtrade(record, path, revision=2001)
    with pytest.raises(ValueError, match="one sample rate"):
        rec.write_comtrade(replace(record, sample_rate=None), path)
    with pytest.raises(ValueError, match="a start time"):
        rec.write_comtrade(replace(record, start=None, trigger=None), path)
    va = record.channel("VA")
    holed = replace(va, values=(rec.MISSING, *va.values[1:]))
    with pytest.raises(ValueError, match="VA has missing samples"):
        rec.write_comtrade(replace(record, channels=(holed,), status=()), path)


# ------------------------------------------------------------------------ CSV

def test_waveform_csv(tmp_path):
    record = made(sample_rate=1920.0, duration=0.2)
    lines = ["ms,Bus A (kV),Bus B (kV),Bus C (kV)"]
    for i, t in enumerate(record.times):
        cells = [repr(250.0 + t * 1000.0)] + [repr(ch.values[i])
                                             for ch in record.channels[:3]]
        lines.append(",".join(cells))
    path = tmp_path / "wave.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    got = rec.read_csv(
        path, time="ms", time_scale=0.001, nominal_frequency=60.0,
        channels={"VA": "Bus A (kV)", "VB": "Bus B (kV)", "VC": "Bus C (kV)"},
        units={"VA": "kV", "VB": "kV", "VC": "kV"})
    assert got.name == "wave"
    assert got.names == VOLTS
    assert got.times[0] == 0.0
    assert got.sample_rate == pytest.approx(1920.0)
    assert got.start is None
    low, high = low_high(got)
    assert low.minimum() == pytest.approx(1.0, abs=1e-9)
    assert high.maximum() == pytest.approx(1.0, abs=1e-9)
    plain = rec.read_csv(path, time="ms", time_scale=0.001,
                         nominal_frequency=60.0, channels=["Bus A (kV)"])
    assert plain.names == ("Bus A (kV)",)
    assert plain.channel("Bus A (kV)").unit == ""


def test_csv_problems_are_named(tmp_path):
    path = tmp_path / "wave.csv"
    path.write_text("t,VA\n0,1\n0.001,2\n", encoding="utf-8")
    with pytest.raises(KeyError, match="no column 'VB'"):
        rec.read_csv(path, time="t", channels=["VB"], nominal_frequency=60.0)
    with pytest.raises(KeyError, match="no column 'seconds'"):
        rec.read_trace_csv(path, time="seconds", value="VA")
    short = tmp_path / "short.csv"
    short.write_text("t,VA\n0,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fewer than two rows"):
        rec.read_csv(short, time="t", channels=["VA"], nominal_frequency=60.0)


def test_uneven_csv_has_no_sample_rate(tmp_path):
    path = tmp_path / "wave.csv"
    path.write_text("t,VA\n0,1\n0.001,2\n0.003,3\n", encoding="utf-8")
    got = rec.read_csv(path, time="t", channels=["VA"], nominal_frequency=60.0)
    assert got.sample_rate is None


def test_trace_csv(tmp_path):
    path = tmp_path / "rms.csv"
    path.write_text("﻿Time (s),V (kV)\n10.0,230\n10.5,115\n11.0,230\n",
                    encoding="utf-8")
    trace = rec.read_trace_csv(path, time="Time (s)", value="V (kV)",
                               value_scale=1.0 / KV)
    assert trace.times == [0.0, 0.5, 1.0]
    assert trace.values == pytest.approx([1.0, 0.5, 1.0])
    assert trace.time_below(0.9) == pytest.approx(0.5)


# ------------------------------------------------------------------ alignment

def test_records_line_up_by_their_start_times():
    first = made(duration=0.1, start=datetime(2026, 3, 9, 14, 5, 6, 0))
    second = made(duration=0.1, start=datetime(2026, 3, 9, 14, 5, 6, 250000))
    assert rec.align([second, first]) == (0.25, 0.0)
    moved = second.shifted(-0.05)
    assert rec.align([first, moved]) == pytest.approx((0.0, 0.2))
    trace = rec.shift(Trace([0.0, 1.0], [1.0, 0.9]), 0.25)
    assert trace.times == [0.25, 1.25] and trace.values == [1.0, 0.9]


def test_records_that_state_utc_offsets_are_compared_in_utc():
    start = datetime(2026, 3, 9, 14, 5, 6)
    india = replace(made(duration=0.1, start=start),
                    utc_offset=timedelta(hours=5, minutes=30))
    utc = replace(made(duration=0.1, start=start - timedelta(hours=5, minutes=30)
                       + timedelta(seconds=1)), utc_offset=timedelta(0))
    assert rec.align([india, utc]) == (0.0, 1.0)


def test_alignment_refuses_to_guess():
    start = datetime(2026, 3, 9, 14, 5, 6)
    stated = replace(made(duration=0.1, start=start), utc_offset=timedelta(0))
    silent = made(duration=0.1, start=start)
    with pytest.raises(ValueError, match="some do not"):
        rec.align([stated, silent])
    with pytest.raises(ValueError, match="needs a start time"):
        rec.align([silent, replace(silent, start=None)])
    with pytest.raises(ValueError, match="at least one record"):
        rec.align([])
    with pytest.raises(ValueError, match="no start time to shift"):
        replace(silent, start=None).shifted(1.0)


def test_shifting_moves_the_trigger_with_the_start():
    record = event().shifted(2.0)
    assert record.start == datetime(2026, 3, 9, 14, 5, 8, 123456)
    assert record.trigger_time == pytest.approx(0.1)


# ------------------------------------------------------------------ the record

def test_a_record_checks_itself():
    with pytest.raises(ValueError, match="does not match the time base"):
        rec.Recording("x", (0.0, 1.0), (rec.Channel("VA", (1.0,)),), 60.0)
    with pytest.raises(ValueError, match="status TRIP does not match"):
        rec.Recording("x", (0.0, 1.0), (), 60.0, status=(rec.Status("TRIP", (1,)),))
    with pytest.raises(ValueError, match="at least two samples"):
        rec.Recording("x", (0.0,), (), 60.0)
    record = made(duration=0.1)
    assert record.trigger_time is None
    with pytest.raises(KeyError, match="this record has"):
        record.channel("VN")


def test_the_synthetic_record_is_what_it_says():
    record = made(megawatts=[(0.0, 90.0)])
    assert record.names == (*VOLTS, *AMPS)
    assert {ch.unit for ch in record.channels} == {"kV", "kA"}
    assert len(record.times) == 3841
    peak = max(record.channel("VA").values)
    assert peak == pytest.approx(LINE_TO_NEUTRAL * math.sqrt(2.0), rel=1e-9)
    # 90 MW at 230 kV and unity power factor is 90 / (sqrt(3) * 230) kA.
    amps = max(record.channel("IA").values) / math.sqrt(2.0)
    assert amps == pytest.approx(90.0 / (math.sqrt(3.0) * KV), rel=1e-9)


# -------------------------------------------------------------------- the docs

def test_the_example_in_the_docs_prints_what_the_docs_say(tmp_path):
    page = Path(__file__).resolve().parent.parent / "docs" / "RECORDINGS.md"
    blocks = re.findall(r"```(python)?\n(.*?)```", page.read_text(encoding="utf-8"),
                        flags=re.S)
    code = next(body for kind, body in blocks if kind == "python")
    printed = next(body for kind, body in blocks if kind != "python")
    out = io.StringIO()
    before = os.getcwd()
    os.chdir(tmp_path)
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(code, str(page), "exec"), {"__name__": "docs"})
    finally:
        os.chdir(before)
    assert out.getvalue() == printed
    assert (tmp_path / "event.dat").exists()
