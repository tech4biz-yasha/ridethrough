# ridethrough

[![CI](https://github.com/tech4biz-yasha/ridethrough/actions/workflows/ci.yml/badge.svg)](https://github.com/tech4biz-yasha/ridethrough/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23622860.svg)](https://doi.org/10.5281/zenodo.23622860)

An open grader for data centre voltage ride-through claims.

Describe a facility. It throws the disturbance a grid code requires at it,
tells you whether the facility stays on, and if not, which obligation failed
and which piece of equipment gave up first.

## Why

AI data centres protect themselves. When grid voltage dips for a fraction of
a second, their protection trips and they disconnect. On 22 July 2026 roughly
3.8 GW of data centre load in Dominion's territory dropped off after a fault
that was cleared exactly as designed. Four weeks later FERC ordered NERC to
file reliability standards for computational loads by the end of the year.

From 2027, large computational load sites in North America have to show a
system operator that they ride through. ERCOT already requires it. Model
quality testing, converter model validation, the lot.

There is no open, reproducible way to check whether a submitted claim holds
up. This is that check.

## Install

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

No simulation licence. No commercial solver. Pure Python, no dependencies.

## Grade your own facility

Write what you know about your site. Hold-up time, not capacitance. Current
limit as a multiple of normal. Battery in minutes.

```json
{
  "name": "Site A, 120 MW",
  "rated_power_mw": 120,
  "cooling_fraction": 0.25,
  "psu": {"hold_up_ms": 10, "current_limit_pu": 1.5, "restart_s": 120},
  "ups": {"hold_up_ms": 50, "current_limit_pu": 1.2},
  "battery": {"minutes": 5},
  "protection": {"undervoltage_pickup_pu": 0.85, "delay_s": 0.1}
}
```

```
ridethrough check site-a.json
```

```
facility: Weak site, 80 MW, no UPS
code:     ERCOT NOGRR282

  0.85 pu held     2 s   pass
  0.80 pu held     2 s   trips           undervoltage protection trip
  0.75 pu held   0.5 s   trips           undervoltage protection trip
  0.50 pu held   0.5 s   trips           server PSU undervoltage lockout
  0.45 pu held  0.25 s   trips           server PSU undervoltage lockout
  0.35 pu held  0.25 s   trips           server PSU undervoltage lockout
  0.30 pu held  0.15 s   trips           server PSU undervoltage lockout
  0.00 pu held  0.15 s   trips           server PSU undervoltage lockout

overall: trips
```

Each row is a flat sag held for exactly as long as that code allows at that
depth, which is the worst case it actually requires. The right hand column is
what physically gave up, which is the part nobody publishes.

Only `name`, `rated_power_mw` and `psu` are required. Leave out the UPS and
the model runs without one, which is itself a revealing configuration.

## In CI

```yaml
- uses: tech4biz-yasha/ridethrough@main
  with:
    facility: site-a.json
    code: ercot
```

The step fails if any corner trips. Put it next to the model you submit and
you find out before the system operator does.

## The public table

```
ridethrough sweep
```

```
code: ERCOT NOGRR282
archetype                 0.85/2s  0.80/2s  0.75/0.5s  0.50/0.5s  0.45/0.25s  0.35/0.25s  0.30/0.15s  0.00/0.15s
----------------------------------------------------------------------------------------------------------------
no-ups                       pass     pass       pass       TRIP        TRIP        TRIP        TRIP        TRIP
no-ups-relay                 pass     TRIP       TRIP       TRIP        TRIP        TRIP        TRIP        TRIP
ups                          pass     TRIP       TRIP       TRIP        TRIP        TRIP        TRIP        TRIP
ups-battery                  pass     pass       pass       pass        pass        pass        pass        pass
ups-battery-reduction        pass     pass       pass       pass        pass        pass        pass        pass
ups-sag-counter              pass     pass       pass       pass        pass        pass        pass        pass
```

Every scorecard, every code, one command:

```
ridethrough run
```

## The northern Virginia failure mode

The last row above passes everything. Now give it the reclosing train that
actually happens:

```
ridethrough repeated ups-sag-counter
```

```
verdict: trips
driver:  stays connected
physics: sag-counting scheme trip at 39500 ms
  [pass] envelope: 6 separate excursions, each inside the envelope (deepest 0.300 pu)
  [FAIL] stays connected: disconnected during the event
```

A site with a scheme that transfers after four sags in a minute passes every
single-sag test and fails the train. That is the behaviour ERCOT Section
2.15(7) now forbids, reproduced from first principles rather than quoted
from an incident report.

## Reclosing

A recloser does not fire once. It fires instantaneously, then after its
first delay, then after its second. That is the pattern facilities actually
see, and it is the one they actually fail.

```
ridethrough reclosing
```

```
pattern: 10 July 2024 Dominion event as reported to ERCOT LLWG
         0.683 pu for 75 ms, six sags, reclosing at 20 s and 80 s
code:    ERCOT NOGRR282

  no-ups                   trips          current ceiling
  no-ups-relay             trips          current ceiling
  ups                      rides through
  ups-battery              rides through
  ups-battery-reduction    rides through
  ups-sag-counter          trips          stays connected      sag-counting scheme trip at 21.0 s
```

The magnitude, duration, count and reclosing delays are transcribed from
Dominion Energy, *An Overview of Data Centers Response to the Recent Large
Load Events in Dominion Energy*, Narges Ghiasi and Francisco A Zelaya,
presented to the ERCOT Large Load Working Group on 15 October 2026. The deck
does not give the individual sag timestamps, so their placement is ours.

Two things this showed, both pinned as tests. At that magnitude and duration
stored energy is not the failure mechanism, because the sag is too shallow
and too short to drain a bus that refills between shots. What fails instead
is either a current limit above the 150% ceiling or a scheme that counts
sags, and for the counting scheme the answer depends on where the window
falls: the pattern puts four sags inside one minute and two more well
outside it, so a counter set at four trips on the fourth and a counter set
at five never trips at all.

Nothing here reproduces the behaviour of any named facility.

## The codes

```
ridethrough codes
ridethrough sweep --code energinet
```

| key | envelope | current ceiling | recovery |
| --- | --- | --- | --- |
| `ercot` | band table | 1.50 x normal | 90% in 2 s |
| `ercot-2028` | band table | 1.50 x normal | 90% in 2 s |
| `energinet` | voltage against time | none, blocking permitted | 80% in 5 s, 90% in 20 s, 95% in 30 s |

The current column is not a detail. ERCOT caps the current a facility may
draw during a disturbance. Energinet Section 11(2) explicitly permits current
blocking and sets no ceiling at all. A facility that satisfies one of them on
current has told you nothing about the other.

`ercot-2028` differs in one place. Section 2.15(3)(c)(ii) moves the floor
below which a facility may stop drawing power from 0.80 pu to 0.50 pu, for
facilities qualifying after 1 January 2028.

## Frequency

Section 2.6.4 is graded separately, because the rule is separate.

```python
from ridethrough import grade_frequency
```

Three obligations: the table, the requirement to keep consuming current, and
the frequency transfer route. The clause saying a facility "should" stay
within 10% of its pre-disturbance power is reported and not scored, because
the rule says should rather than shall.

## Checking the numbers against the rule

A claim that the values come from the rule is worth less than a script that
checks it, so both ship with the package.

```
python validate/check_tables.py
python validate/check_scalars.py
```

The first parses Table A out of the rule text in `validate/` and asserts
this package returns the stated minimum ride-through time at both edges of
every band. The second asserts each constant against a quoted sentence from
the source, and confirms the superseded draft values are absent. Both run in
CI. `validate/coverage.md` lists every clause of both sections and marks it
graded or out of scope.

## What is not graded, and why

Seven clauses are declared out of scope with a reason, carried on each code
object rather than only in a document:

```python
from ridethrough import ERCOT
for clause, reason in ERCOT.out_of_scope:
    print(clause, reason)
```

They are the exemption criteria, the protection-setting requirements, the
failure investigation process, the UFLS carve-out, the "if capable"
proportional reduction in 2.15(3)(c)(i), the per-device action count in
2.15(3)(e)(i), and the 2.15(3)(f) overvoltage trip allowance.

Four places where the rule does not settle how it applies are carried as
open questions and reported rather than resolved:

```python
for q in ERCOT.open_questions:
    print(q)
```

## Verdicts

- `rides through` - every obligation met.
- `trips` - at least one obligation failed. `trip_driver` names the first.
- `not required` - the disturbance fell outside the envelope, so the code did
  not require ride-through. Not a failure.
- `error` - the run tested nothing, for example a trace that never leaves the
  continuous operating range. Never silently a pass.

Exit codes follow: 0, 1, 2, 3.

## Where the numbers come from

Every ERCOT value is transcribed from the published rule: **ERCOT Nodal
Operating Guide Section 2, file `02-080126.docx`, effective 1 August 2026**,
Sections 2.6.4 and 2.15. Definitions come from Nodal Protocols Section 2.1
as amended by NPRR1308. Both were approved by the Public Utility Commission
of Texas on 9 July 2026 in Project No. 54445.

Section 2.15(3), Table A:

| RMS voltage (pu of nominal) | Minimum ride-through time |
| --- | --- |
| V > 1.20 | may ride through or trip |
| 1.10 < V <= 1.20 | 1.0 s |
| 0.90 <= V <= 1.10 | continuous |
| 0.80 <= V < 0.90 | 2.0 s |
| 0.50 <= V < 0.80 | 0.5 s |
| 0.35 <= V < 0.50 | 0.25 s |
| V < 0.35 | 0.15 s |

Section 2.6.4(3), Table A:

| Frequency (Hz) | Minimum ride-through time |
| --- | --- |
| f > 63.0 | may ride through or trip |
| 61.2 < f <= 63.0 | 299 s |
| 58.8 <= f <= 61.2 | continuous |
| 57.5 <= f < 58.8 | 299 s |
| f < 57.5 | may ride through or trip |

Current ceiling, 2.15(3)(d): 150% of maximum normal current, and the
overcurrent may persist no more than 0.5 seconds.

Recovery, 2.15(3)(b) and (c): at least 90% of pre-disturbance consumption
within two seconds of voltage returning above 0.90 pu.

Transfer route, 2.15(3)(e): begin returning within 0.25 seconds and reach
90% within 0.5 seconds. Tighter than the general route, so declaring a
transfer scheme makes the obligation harder rather than easier.

Cooling, 2.15(3): cooling or mechanical load may trip below 0.35 pu for any
duration, and tripped cooling is subtracted from pre-disturbance consumption
when recovery is judged.

Repeated sags, 2.15(7): a facility forced to use a counting scheme must
survive at least six sags in 90 seconds.

Energinet Technical Regulation 3.4.3, Revision 1, effective
1 November 2024. UV-FRT from Section 11(2), Table 2:

| point | voltage (pu) | time (s) |
| --- | --- | --- |
| Uret | 0 | tclear 0.15 |
| Uclear | 0.35 | trec1 0.15 |
| Urec1 | 0.35 | trec2 0.55 |
| Urec2 | 0.90 | trec3 1.5 |

The full method, with each statement tied to its clause or its file, is in
[docs/METHOD.md](docs/METHOD.md).

## How the model works

The chain is grid, then optionally a UPS, then the server power supplies,
then the IT load, with cooling following through a thermal lag.

Each energy store is given by its hold-up time at rated power rather than its
capacitance, because hold-up is what a facility can state and what system
operators ask them to inventory. Capacitance follows from it.

Every stage draws constant power behind a current limit. That is the whole
reason these sites are hard on a grid: as voltage falls, current rises to
hold power. The limit stops it and the shortfall comes out of the store. How
long the store lasts is

```
store lasts = hold-up time / (demand - voltage x current limit)
```

The tests check simulated trip times against that arithmetic rather than
against recorded output, so the model cannot drift without the suite
breaking.

Two things that came out of building it, both pinned as tests:

A facility whose converter current limit sits below 1.25 pu can never fail
the ERCOT current obligation at any sag depth. It limits itself and runs out
of stored energy instead. Where a site fails depends on its current limit,
not only on how much energy it stores.

A constant power load draws 1/V, so the 150% ceiling binds at exactly
0.667 pu. Above that a facility can hold constant power inside the ceiling;
below it, it cannot.

## The one interpretation we made

A band table is unambiguous for a rectangular sag. For an arbitrary trace
this grader reads it as: the disturbance stays inside the envelope if, for
every band, the total time spent below that band's upper edge does not exceed
that band's minimum ride-through time.

That reading is ours. It has not been confirmed by ERCOT. It is the first
question we intend to put to the ERCOT Large Load Working Group.

Building the repeated-sag case showed why it matters. Summed across a whole
trace, six separate 60 ms sags look like one 360 ms excursion, which is
beyond what the band allows, so the grader wrongly concluded the facility was
free to trip. Section 2.15(7) is explicit that each condition must be
ridden through separately. The trace is now split into separate excursions
and each is measured on its own. Both the old behaviour and the fix are
pinned as tests.

## What this is not

This is an averaged model. It carries energy and power at the millisecond
scale. It does not resolve point-on-wave switching, harmonics, phase
imbalance or sub-cycle protection behaviour. For a question that lives
between ten milliseconds and a few seconds, that is the right resolution. For
anything faster it is the wrong tool and you want an EMT solver.

It does not perform converter model validation against hardware. That needs a
laboratory, and this project does not claim it.

It does not issue compliance approval. It produces evidence.

The archetypes are configurations, not sites. Nothing in this repository is a
measurement of any real facility.

Not yet covered from the sources: Energinet's LFSM-U requirement in
Section 13 and its phase jump requirement in Section 9.

## Submit a facility

Open an issue using the "Submit a facility" template. No pull request needed.
The shape, the verdicts and the trip drivers get published. Your site name,
location and operator do not, unless you ask for them to be. Nothing goes up
until you have confirmed the reproduced numbers.

## Layout

```
ridethrough/      the package
  envelope.py     envelopes, as band tables and as voltage-time curves
  codes.py        grid codes: envelope plus obligations
  grade.py        the grader
  facility.py     the facility model
  archetypes.py   six configurations, with their provenance
  spec.py         build a facility from JSON
  cli.py          check, run, sweep, simulate, repeated, reclosing, grade, codes
validate/         the rule text, and scripts that check the package against it
docs/METHOD.md    the method, statement by statement
tests/            202 tests
results/          one generated scorecard per code
examples/         a facility description and two hand-written runs
action.yml        the GitHub Action
```

## Develop

```
ruff check .
python -m pytest -q
```

## Cite

Khandelwal, Yasha. *ridethrough: an open grader for data centre
voltage ride-through claims*, version 0.6.0, 2026.
DOI [10.5281/zenodo.23622860](https://doi.org/10.5281/zenodo.23622860)

Machine-readable metadata is in `CITATION.cff`.

MIT. Copyright 2026 Yasha Khandelwal.
