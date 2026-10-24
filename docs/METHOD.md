# Method

How a ride-through claim is graded here, what the model does, and what each
statement in this document rests on.

Statements below are marked in one of two ways. A **code statement** is
transcribed from a published grid code and the section is named. A **model
statement** describes what this software does and can be checked against the
file named. Nothing here rests on a measurement, because nothing in this
repository is measured.

---

## 1. The question

A grid code asks three things of a large load during a voltage disturbance.
Stay connected. Keep drawing power, or do not draw too much. Come back to
normal consumption in time.

A facility answers those three questions with a model it submits to a system
operator. There is no open, reproducible way to check whether the answer
holds up. This tool is that check.

---

## 2. What the grader takes and what it returns

**Model statement** (`ridethrough/grade.py`). The grader takes four traces
sampled over time, plus two scalars.

| input | meaning |
| --- | --- |
| `voltage` | RMS positive sequence voltage in pu at the service delivery point |
| `connected` | 1.0 while the facility is connected, 0.0 once it is not |
| `active_power` | active power drawn from the grid |
| `current` | current drawn from the grid, in pu of normal |
| `pre_disturbance_power` | the level the facility was at before the event |
| `max_normal_current` | the most current it draws in normal operation |

Samples are held between points.

**Model statement** (`ridethrough/grade.py`). It returns one of four verdicts.

| verdict | meaning |
| --- | --- |
| `rides through` | every obligation met |
| `trips` | at least one obligation failed; `trip_driver` names the first |
| `not required` | the disturbance fell outside the envelope, so the code did not require ride-through |
| `error` | the run tested nothing, or the input is malformed |

`error` exists so that a run which never leaves the continuous operating
range cannot be reported as a pass. It is never a silent success.

---

## 3. Deciding whether ride-through was required at all

A code states its envelope in one of two shapes.

**Code statement** (ERCOT Section 2.14(2), Table A). A band table: each
voltage range carries a minimum ride-through time.

**Code statement** (Energinet TR 3.4.3 Section 11(2), Table 2). A floor
against time measured from fault inception, rising through the stated points.

**Model statement** (`ridethrough/grade.py`, `excursions`). The voltage trace
is first split into the separate times it leaves the continuous operating
range. A train of reclosing sags is several disturbances, not one long one.

**Code statement** (ERCOT Section 2.14(2)(6)). A facility may not implement a
scheme that trips on a count of sags it is required to ride through, which
establishes that each sag is its own condition.

**Model statement**. Each excursion is then measured on its own. For a band
table, an excursion stays inside the envelope if, for every band, the time
spent below that band's upper edge does not exceed that band's minimum
ride-through time. For a floor against time, the retained voltage must sit on
or above the floor at every moment after inception.

**This reading has not been confirmed by either system operator.** A band
table is unambiguous for a rectangular sag. Applying it to an arbitrary trace
requires a choice, and the choice above is ours. It is the first question we
intend to put to the ERCOT Large Load Working Group.

---

## 4. The obligations

### Stay connected

**Code statement** (ERCOT Section 2.14(2)). The facility shall remain
connected to the transmission grid during voltage conditions requiring
ride-through.

**Code statement** (Energinet Section 11). The facility must withstand a
voltage dip without disconnecting from the transmission system.

### Current

**Code statement** (ERCOT Section 2.14(2)(d)). During a disturbance outside
the continuous operating range, the facility shall not consume current above
125% of its maximum current in normal operations.

**Code statement** (Energinet Section 11(2)). Current blocking under
undervoltage ride-through is permitted. No ceiling is stated.

A facility that satisfies one of these on current has told you nothing about
the other.

### Keep drawing power

**Code statement** (ERCOT Section 2.14(2)(b)). Between 0.80 and 0.90 pu, with
voltage returning above 0.90 pu within two seconds, the facility shall
continue consuming active power during the low voltage condition.

**Code statement** (ERCOT Section 2.14(2)(c)(ii)). For facilities qualifying
after 1 January 2028, the facility shall continue consuming between 0.80 and
0.50 pu, and may reduce as needed below 0.50 pu.

**Model statement** (`ridethrough/codes.py`). This is the only difference
between the `ercot` and `ercot-2028` codes in this tool: the floor moves from
0.80 pu to 0.50 pu.

### Recover

**Code statement** (ERCOT Sections 2.14(2)(b) and (c)). Return to at least
90% of pre-disturbance consumption within two seconds of voltage returning
above 0.90 pu.

**Code statement** (Energinet Section 12(2)). At least 80% within five
seconds, 90% within twenty seconds and 95% within thirty seconds of normal
operating conditions being restored, each with a tolerance of 2% of rated
power.

**Code statement** (Energinet Section 12(2)(d)). Overshoot above the
pre-incident level is limited to 10% of rated power in the first five seconds
and 5% after that.

---

## 5. The facility model

**Model statement** (`ridethrough/facility.py`). The chain is grid, then
optionally a UPS, then the server power supplies, then the IT load, with
cooling following the IT load through a first-order lag.

**Model statement**. Each energy store is specified by its hold-up time at
rated power, not its capacitance. Capacitance follows from

    C = 2 P t / (V_nom^2 - V_cut^2)

Hold-up time is chosen as the input because it is what a facility can state
and what system operators ask operators to inventory. Capacitance is not.

**Model statement**. Every stage draws constant power behind a current limit.
As voltage falls, current rises to hold power. The current limit stops it,
and the shortfall then comes out of the store. How long the store lasts is

    store lasts = hold-up time / (demand - voltage x current limit)

The tests in `tests/test_facility.py` check simulated trip times against that
arithmetic rather than against recorded output, so the model cannot drift
without the suite breaking.

**Model statement**. The model reports which element gave up first, separately
from the grader's verdict: server PSU undervoltage lockout, UPS DC bus
collapse, battery depleted, undervoltage protection trip, or a sag-counting
scheme trip. The grader says which obligation failed. The model says what
inside the building failed. They answer different questions and both are
reported.

---

## 6. What this is not

This is an averaged model. It carries energy and power at the millisecond
scale. It does not resolve point-on-wave switching, harmonics, phase
imbalance or sub-cycle protection behaviour. For a question that lives
between ten milliseconds and a few seconds, that is the right resolution. For
anything faster it is the wrong tool and an EMT solver is the right one.

It does not perform converter model validation against hardware. That needs a
laboratory, and this project does not claim it.

It does not issue compliance approval. It produces evidence.

The archetypes shipped with it are configurations, not sites. Nothing in this
repository is a measurement of any real facility.

---

## 7. Two things the model produced

**Model statement**, pinned in `tests/test_facility.py`. A facility whose
converter current limit sits below 1.25 pu cannot fail the ERCOT current
obligation at any sag depth. It limits itself and runs out of stored energy
instead. Where a facility fails depends on its current limit, not only on how
much energy it stores.

**Model statement**, pinned in `tests/test_facility.py`, and agreeing with a
**code statement**. A constant power load draws 1/V, so a 125% ceiling binds
at exactly 0.80 pu. ERCOT's own presentation of Section 2.14(2)(d) states on
the same slide that 125% allows constant power for voltage sags down to
0.8 pu.

---

## 8. Sources

ERCOT, *Large Electronic Load Ride-Through Requirements, NOGRR 282 and
NPRR 1308*, Patrick Gravois, SPWG, 24 February 2026. Sections 2.6.4 and 2.14.

Energinet, *Technical Regulation 3.4.3, Requirements for
Transmission-Connected Demand Facilities, Revision 1*, effective
1 November 2024. Sections 11, 12 and 13.

Author: Yasha Khandelwal, yasha.khandelwal@tech4biz.io
