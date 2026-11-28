# Reading recorder files

A ride-through rule is written in fundamental RMS voltage, frequency, rate
of change of frequency, phase angle and Real Power. A fault recorder stores
none of those. It stores instantaneous samples of voltage and current.
`ridethrough/recording.py` reads the file and does the arithmetic in
between.

It stops there. Nothing on this page grades a generator against a rule.

## What it reads

| File | Function | Notes |
| --- | --- | --- |
| COMTRADE `.cfg` with `.dat` | `read_comtrade` | The 1991, 1999 and 2013 configuration layouts. Data as `ASCII` or `BINARY`, and as `BINARY32` or `FLOAT32` under a 2013 configuration |
| CSV of sampled waveforms | `read_csv` | A header row, a time column, one column per channel |
| CSV of one computed quantity | `read_trace_csv` | For RMS voltage, megawatts or frequency already worked out by a relay, a PMU or a SCADA historian |

It does not read the single-file COMTRADE `.cff`, the `.hdr` and `.inf`
files that can sit beside a record, inverter manufacturers' own log
formats, or live PMU streams.

## A short example

This writes a made-up event to a COMTRADE file, reads it back as a recorder
file would be read, and prints what the rule needs.

```python
from datetime import datetime

from ridethrough import recording as rec
from ridethrough.prc029 import PRC029_TABLE_2_OTHER

# 230 kV, 100 MW. All three phases at 0.5 per unit from 0.3 s to 0.5 s.
event = rec.synthetic_recording(
    sample_rate=3840.0, duration=1.0, nominal_frequency=60.0, nominal_kv=230.0,
    voltage_pu=[(0.0, 1.0), (0.3, 0.5), (0.5, 1.0)],
    megawatts=[(0.0, 100.0)], start=datetime(2026, 3, 9, 14, 5, 6))
rec.write_comtrade(event, "event.cfg")

record = rec.read_comtrade("event.cfg")
phases = ("VA", "VB", "VC")
low, high = rec.voltage_per_unit(
    record, channels=phases, nominal_kv=230.0, basis=rec.PHASE_TO_NEUTRAL)
power = rec.real_power(record, voltages=phases, currents=("IA", "IB", "IC"))
a, b, c = (rec.phasors(record, name) for name in phases)
hertz = rec.frequency(rec.positive_sequence(a, b, c), cycles=6)
found = rec.deviations(low, high, PRC029_TABLE_2_OTHER)

print(f"lowest voltage       {low.minimum():.3f} pu")
print(f"time below 0.90 pu   {low.time_below(0.90):.4f} s")
print(f"deviations           {[(round(s, 4), round(e, 4)) for s, e in found]}")
print(f"power at 0.4 s       {power.at(0.4):.1f} MW")
print(f"frequency at 0.4 s   {hertz.at(0.4):.2f} Hz")
```

```
lowest voltage       0.500 pu
time below 0.90 pu   0.2125 s
deviations           [(0.3018, 0.5143)]
power at 0.4 s       100.0 MW
frequency at 0.4 s   60.00 Hz
```

The sag was 0.2000 s long and reads as 0.2125 s. That is the one-cycle
window at work, and the section on it below gives the size of the effect.

## How each quantity is computed

| Quantity | Function | How |
| --- | --- | --- |
| Fundamental phasor | `phasors` | At each sample, a constant plus a sine and a cosine at the nominal frequency are fitted by least squares to the last cycle of samples. The constant takes up any DC offset. Each result carries the time of the last sample in its window |
| Fundamental RMS | `rms` | The size of that phasor |
| Phase-to-phase voltage | `phase_to_phase` | One phase phasor minus another |
| Lowest and highest voltage, per unit | `voltage_per_unit` | The RMS of the three phase-to-neutral voltages, or of the three phase-to-phase voltages, divided by the base. Then the lowest and the highest of the three at each sample |
| Positive sequence voltage | `positive_sequence` | (Va + a·Vb + a²·Vc) / 3, where a turns a phasor by 120 degrees |
| Phase angle | `angle_degrees` | The angle of a phasor against a reference turning at the nominal frequency, unwrapped |
| Phase angle jump | `angle_jump` | The change in angle over a period you state, less the change over the period before it |
| Frequency | `frequency` | The nominal frequency plus the rate at which a phasor's angle turns, over a number of cycles you state. Give it the positive sequence phasor |
| Rate of change of frequency | `rate_of_change` | The change in frequency over the period you state before each sample, divided by the time that change took |
| Real Power | `real_power` | The products of each phase-to-neutral voltage and its line current, added, averaged over the last cycle, in megawatts |
| Deviations | `deviations` | Each stretch where the lowest or the highest voltage sits in a row of the table that is not in the continuous operation region |
| Event window | `event_window` | From the start of the first deviation to the end of the last |

Five of these follow wording in NERC PRC-029-2, and you have to make the
choice the wording leaves open.

**Which voltage.** Attachment 1, item 5 (page 15) says the applicable
voltage is "the voltage max/min of phase-to-neutral or phase-to-phase
fundamental root mean square (RMS) voltage at the high-side of the main
power transformer". It says "or" and does not pick one, so
`voltage_per_unit` has no default. You pass `basis=PHASE_TO_NEUTRAL` or
`basis=PHASE_TO_PHASE`. The two give different answers in an unbalanced
fault. With one phase at 0.5 per unit and the other two at 1.0, the lowest
phase-to-neutral voltage is 0.500 per unit and the lowest phase-to-phase
voltage is 0.764 per unit.

`voltage_per_unit` takes the three phase-to-neutral channels and works out
the phase-to-phase voltages from them. If the recorder holds phase-to-phase
channels instead, do not pass them to it. Take `rms(phasors(...))` of each,
divide by `nominal_kv` with `per_unit`, and pass the three results to
`lowest` and `highest`.

**Which base.** Item 4 of the same attachment says the base "is the nominal
phase-to-ground or phase-to-phase transmission system voltage unless
otherwise defined by the Planning Coordinator, Transmission Planner, or
Transmission Owner". You pass
`nominal_kv`, the nominal phase-to-phase voltage. Phase-to-neutral readings
are divided by `nominal_kv / √3` and phase-to-phase readings by
`nominal_kv`.

**How long a frequency measurement is.** Attachment 2, item 2 (page 17) says
"Frequency is measured over a period of time (typically 3-6 cycles)". The
number of cycles is yours to state, so `frequency` has no default either.

**How rate of change is averaged.** Footnote 9 to R3 (page 5) says the rate
"is calculated as the average rate of change for multiple calculated system
frequencies for a time period of greater than or equal to 0.1 second". You
pass the period to `rate_of_change`. The same footnote says the rate "is not
calculated during the fault occurrence and clearance". `rate_of_change`
leaves no period out. Which samples to leave out is a grading decision.

**Over what time a phase angle change is taken.** R1 (page 2) excepts an
event where "The instantaneous positive sequence voltage phase angle change
is more than 25 electrical degrees at the high-side of the main power
transformer and is initiated by a non-fault switching event on the
transmission system". Neither that sentence nor its footnote gives a time
over which the change is measured. You pass the period to `angle_jump`.
Make it at least one cycle. A phasor here is one cycle wide, and with a
period of half a cycle a 25 degree jump reads as 12.5 degrees.

`deviations` carries a reading of this package's own. Attachment 1, item 9
allows a trip "for more than four deviations of the applicable voltage at
the high-side of the main power transformer outside of the continuous
operation region within any 10 second time period", and does not say where
one deviation ends and the next begins. Here a deviation starts at the first
sample where the lowest or highest voltage is outside the continuous
operation region and ends at the first later sample where both are back in
it.

## What the one-cycle window does to the answer

Every figure below is pinned by a test in `tests/test_recording.py`. Unless
it says otherwise, it is for a 60 Hz record at 3,840 samples a second.

1. The first cycle of a record gives no values. The first phasor is at the
   last sample of the first cycle.
2. A step in voltage takes one cycle to show in full, because the window
   holds samples from before and after the step until it has moved past it.
3. A duration read off these traces can be out by up to one cycle, 16.7 ms
   at 60 Hz, in either direction. A sag to 0.50 per unit lasting 0.2000 s
   reads as 0.2125 s below 0.90 per unit. A sag to 0.89 per unit lasting
   0.2000 s reads as 0.1911 s.
4. When the system frequency is away from the frequency fitted, each
   phase's reading swings up and down twice a cycle around the true value.
   The lowest phase then reads low and the highest reads high.

   | System frequency | Lowest reads | Highest reads |
   | --- | --- | --- |
   | 59.9 Hz | 0.08% low | 0.08% high |
   | 59.5 Hz | 0.43% low | 0.41% high |
   | 58.8 Hz | 1.08% low | 0.95% high |
   | 57.0 Hz | 2.97% low | 2.15% high |
   | 60.5 Hz | 0.43% low | 0.40% high |
   | 61.8 Hz | 1.63% low | 1.33% high |

   Where a record sits at one off-nominal frequency throughout, pass that
   frequency as `at_frequency` and the swing goes. A 59.5 Hz record fitted
   at 59.5 Hz reads 1.000 per unit on every phase. On balanced voltages
   the positive sequence does not swing. At 59.5 Hz it reads a steady
   0.9999 per unit, and frequency taken from it reads 59.500 Hz. Frequency
   taken from one phase alone swings between 59.496 and 59.504 Hz.
5. A sample rate that is not a whole number of samples per cycle is fine
   for a clean sine wave. 10,000 samples a second at 60 Hz reads 1.000 per
   unit. With a harmonic present, a little of it leaks into the reading. A
   fifth harmonic at 10% of the fundamental moves a 10,000 samples a second
   reading by up to 0.04%. At a whole number of samples per cycle it moves
   it by nothing.
6. Real Power is sensitive to the sample rate in the same way. With one
   phase delivering half the power of the other two, a true 83.33 MW reads
   between 83.30 and 83.37 MW at 10,000 samples a second, and reads
   83.33 MW at 3,840.
7. A sudden phase angle jump also shows as a short frequency excursion.
   A 25 degree jump reads as 25.0 degrees from `angle_jump`, and it lifts a
   six-cycle frequency measurement by 0.69 Hz for about six cycles.
   `angle_jump` shows a jump once at its full size and then once more with
   the opposite sign, as the earlier of its two periods passes over the
   same jump.
8. Frequency and phase angle are taken from the positive sequence voltage.
   When that voltage is close to zero, as in a three-phase fault near the
   measuring point, its angle is not a measurement of anything and neither
   is the frequency worked out from it. The module does not blank those
   values. Check the positive sequence RMS over the same period.

## What the COMTRADE reader does

1. A configuration with no revision year on its first line, or with 1991
   there, is read as the 1991 layout, with dates as mm/dd/yy. A later year
   is read with dates as dd/mm/yyyy. A year written with two digits is read
   as 1970 to 2069.
2. Each value is `a × stored value + b`, in the unit the file states. Where
   the file says the result is on the secondary side of an instrument
   transformer, it is multiplied by the primary to secondary ratio in the
   file, so values come back on the primary side. Pass `primary=False` for
   the secondary side. A channel whose ratio fields are empty is left as
   written. A channel with no multiplier `a` stops the read.
3. Time comes from the sample rate in the configuration. Where the
   configuration states no rate, it comes from the time stamps in the data
   file, times the multiplier in the configuration. Stamps count
   microseconds, or nanoseconds when the start time is written to more than
   six decimal places.
4. Missing samples are read as not-a-number. In text data that is an empty
   field, and from the 1999 layout on also the value 99999. In binary data
   from the 1999 layout on it is the most negative value the type can hold.
   In binary data under a 1991 configuration no value is treated as
   missing. `phasors` and `real_power` stop when a channel they are given
   has a missing sample. Nothing fills the gap for you.
5. Binary data under a 1991 configuration is read with the 16-bit layout of
   1999.
6. The time code of the 2013 layout is kept as `utc_offset`. `align` uses it
   to compare start times in UTC when every record has one, compares start
   times as written when none has, and refuses a mix.
7. Text is read as UTF-8, and as Latin-1 if that fails. The end-of-file
   character that some writers add (hex 1A) is dropped.
8. The reader warns when the data file holds fewer samples than the
   configuration states, and stops with the line number when a row of text
   data has the wrong number of fields.
9. Channel skew is not applied. The sample rate in the configuration is
   taken as correct where it is given. A file with more than one sample
   rate is read, with the right times, but `phasors` and `real_power` need
   one rate and say so.

`write_comtrade` exists so that tests and examples can go through the same
file format a recorder writes. It writes 16 bits a sample, so a value read
back can differ from the one written by up to the channel's largest value
divided by 65,534.

## How the reader was checked

1. `tests/test_recording.py` holds a hand-written file for each layout and
   each data type, with the expected values worked out by hand in the test.
2. Records written by `write_comtrade` in all three layouts, as text and as
   binary, read back to within the 16-bit step.
3. `tests/test_recording_crosscheck.py` compares this reader with the
   `comtrade` package by David Parrini (MIT licence), an independent
   COMTRADE reader and writer. Both read six files written here, and six
   written by that package across all four data types, and return the same
   values. That test runs only where `comtrade` is installed, which needs
   Python 3.11 or later. It is not a dependency of this package and the
   test is skipped without it.
4. On 28 November 2026, before this module was committed, both readers
   were also run over the eight pairings of configuration and data files in
   the test folder of that package's GitHub repository, with `comtrade`
   0.3.2, and returned the same values for each.

The reader has not yet been run on files from a plant's own recorders.
Until it has, treat a file from a recorder model it has not seen as
unproven, and compare a few values against the recorder vendor's viewer.

## What is not corrected

The record is taken as it stands. Errors that the voltage and current
transformers add, including the transient response of a capacitive voltage
transformer after a fault, are in the samples and are not removed.
