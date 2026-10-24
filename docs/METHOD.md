# Method

How a ride-through claim is graded here, what the model does, what it does
not do, and where every number comes from.

Statements below are marked in one of three ways. A **rule statement** is
transcribed from a published grid code and the section is named. A **model
statement** describes what this software does and can be checked against the
file named. An **open question** is a place where the rule does not settle
how it applies, and this package reports rather than resolves it.

Nothing here rests on a measurement, because nothing in this repository is
measured.

---

## 1. Sources, and why the provenance is stated this precisely

**ERCOT.** Nodal Operating Guide Section 2, file `02-080126.docx`, effective
1 August 2026, Sections 2.6.4 and 2.15. Definitions from Nodal Protocols
Section 2.1 as amended by NPRR1308. Both approved by the Public Utility
Commission of Texas on 9 July 2026 in Project No. 54445.

**Energinet.** Technical Regulation 3.4.3, Requirements for
Transmission-Connected Demand Facilities, Revision 1, effective
1 November 2024, Sections 11 and 12.

Versions 0.1.0 through 0.5.0 of this package were built from an ERCOT
presentation of NOGRR282 given to the System Protection Working Group on
24 February 2026. That presentation described a draft. Nineteen further sets
of stakeholder comments followed it, from AEP, Tesla, Google, Vistra, TIEC,
the Data Center Coalition and others, and the rule changed before approval.
Six values in those versions were wrong, the section was renumbered from
2.14 to 2.15, and the defined term changed from Large Electronic Load to
Large Computational Load.

A presentation about a rule is not the rule. That is why every value here
names a published document and a clause, and why `validate/check_scalars.py`
asserts each constant against a quoted sentence from the source.

---

## 2. What the grader takes and what it returns

**Model statement** (`ridethrough/grade.py`). `grade` takes four traces and
two scalars, plus three optional facts about the facility.

| input | meaning |
| --- | --- |
| `voltage` | RMS voltage in pu at the Service Delivery Point |
| `connected` | 1.0 while connected, 0.0 once not |
| `active_power` | active power drawn from the grid |
| `current` | current drawn from the grid |
| `pre_disturbance_power` | the level before the event |
| `max_normal_current` | the most current drawn in normal operation |
| `pre_disturbance_cooling_power` | cooling load before the event |
| `cooling_tripped` | whether cooling actually tripped |
| `transfer_scheme` | whether the facility implements 2.15(3)(e) |

**Model statement.** The last three are design facts supplied by the caller.
`transfer_scheme` in particular is never inferred from a trace, because a
facility that dropped out unintentionally would otherwise be graded against
the clause written for one that did so by design.

**Model statement.** `grade_frequency` handles Section 2.6.4 separately,
because the rule is separate: two sections, two tables, two sets of
obligations.

**Model statement.** Four verdicts: `rides through`, `trips`,
`not required`, and `error`. `error` exists so a run that never leaves the
continuous operating range cannot be reported as a pass.

**Model statement.** A check carrying `counts=False` is reported without
deciding the verdict. Each check names the clause it rests on.

---

## 3. Deciding whether ride-through was required

**Rule statement** (ERCOT 2.15(3), Table A). Seven voltage bands, each with
a minimum ride-through time.

**Rule statement** (ERCOT 2.6.4(3), Table A). Five frequency bands.

**Rule statement** (Energinet 11(2), Table 2). A floor against time measured
from fault inception.

**Model statement** (`excursions`). The trace is split into the separate
times it leaves the continuous range, and each is measured on its own.

**Rule statement** (ERCOT 2.15(7)). A facility may not trip on a count of
sags it is required to ride through, and the clause says "each such
condition", which supports measuring each excursion separately.

**Open question.** A band table is unambiguous for a flat sag. For an event
that moves through several bands it needs a reading, and this package uses:
the event stays inside the envelope if, for every band, the total time spent
below that band's upper edge does not exceed that band's minimum time. That
reading is ours.

---

## 4. The voltage obligations, Section 2.15

| clause | obligation | graded |
| --- | --- | --- |
| 2.15(3) | ride through Table A and remain connected | yes |
| 2.15(3) | cooling may trip below 0.35 pu for any duration | yes |
| 2.15(3)(a) | hold pre-disturbance power through overvoltage under 1.0 s | yes |
| 2.15(3)(b) | keep consuming 0.80 to 0.90 pu, 90% within two seconds | yes |
| 2.15(3)(c) | below 0.80 pu, 90% within two seconds, cooling subtracted | yes |
| 2.15(3)(c)(ii) | after 2028, keep consuming 0.80 to 0.50 pu | yes |
| 2.15(3)(d) | current ceiling 150% of maximum normal | yes |
| 2.15(3)(d) | overcurrent duration not to exceed 0.5 s | reported, not scored |
| 2.15(3)(e) | transfer route, 0.25 s to start, 0.5 s to 90% | yes |
| 2.15(7) | no sag counting; six sags in 90 seconds | yes |

**Rule statement** (2.15(3)(d)). "an LCL shall not consume electric current
during the disturbance at a level that exceeds 150% of its maximum electric
current consumption during normal operations. The allowable overcurrent up
to 150% shall only persist during the voltage transient with a duration not
to exceed 0.5 seconds."

**Open question.** 2.15(3)(b) requires a facility to keep consuming for up
to two seconds between 0.80 and 0.90 pu. A constant power load there draws
above normal current for as long as the sag lasts. The duration cap and the
keep-consuming obligation appear to pull against each other, so this package
reports the overcurrent duration and declines to score it.

**Rule statement** (2.15(3)(e)). A facility "may implement a load-transfer
or control stabilization scheme such that the LCL facility begins returning
to the grid within 0.25 seconds... and shall return to at least 90% of its
pre-disturbance consumption level within 0.5 seconds."

**Model statement.** Those deadlines are tighter than the general route's
two seconds, so declaring a transfer scheme makes the obligation harder, not
easier.

**Rule statement** (2.15(3)(c)(ii)). This is the only clause that invokes
the transfer route as relief from the obligation to keep consuming, and it
applies only to facilities qualifying after 1 January 2028. The pre-2028
rule at 2.15(3)(c)(i) never mentions it.

**Open question.** Whether 2.15(3)(e) binds a facility that has a transfer
scheme before 2028, or whether such a facility may rely on the two-second
route, is not settled by the text. This package reports both routes and
scores the transfer route only under the post-2028 code.

**Open question.** 2.15(3)(e)(i) permits one transfer action per disturbance
event per device, and 2.15(7) requires surviving six sags in 90 seconds.
Whether a reclosing train is one disturbance event or several decides
whether a transfer-based design can satisfy both.

---

## 5. The frequency obligations, Section 2.6.4

| clause | obligation | graded |
| --- | --- | --- |
| 2.6.4(3) | ride through Table A | yes |
| 2.6.4(5) | shall keep consuming current | yes |
| 2.6.4(5) | should stay within 10% of pre-disturbance power | reported, not scored |
| 2.6.4(6) | frequency transfer route, 90% within two seconds | yes |

**Rule statement** (2.6.4(5)). "the LCL shall continue to consume electric
current from the grid... In addition, an LCL should continue to consume
active power within 10% of the pre-disturbance level."

**Model statement.** "Shall" is scored. "Should" is reported and not scored.

---

## 6. What this package does not grade, and why

These are carried on each code object as `out_of_scope`, so the list is in
the software rather than only in this document.

**2.15(3)(c)(i).** Reduction below 0.80 pu shall be proportional to the
voltage drop "if capable". The escape clause makes the shape of the
reduction unenforceable from a trace, because a trace cannot show what the
equipment was capable of.

**2.15(3)(e)(i).** One transfer action per disturbance event per individual
device. This package models a facility, not its devices.

**2.15(3)(f).** Before 2028 a facility may trip above 1.08 pu persisting
five seconds or more. That band, 1.08 to 1.10 pu, lies inside the continuous
operating range, so a run exercising it never leaves the envelope and this
package treats such a run as testing nothing.

**2.15(1), 2.15(2), 2.6.4(1), 2.6.4(2).** Exemption criteria, which turn on
interconnection agreements, dates and written attestations.

**2.15(5), 2.15(6), 2.6.4(7), 2.6.4(8).** Protection system settings,
including the one-cycle minimum measurement window. This package grades
outcomes, not settings.

**2.15(8), 2.6.4(9).** The investigation process that follows a failure.

**2.6.4(3).** The UFLS and Ancillary Service carve-out, which depends on
obligations held outside the facility.

---

## 7. The facility model

**Model statement** (`ridethrough/facility.py`). The chain is grid, then
optionally a UPS, then the server power supplies, then the IT load, with
cooling following through a thermal lag.

**Model statement.** Each energy store is given by its hold-up time at rated
power rather than its capacitance, because hold-up time is what a facility
can state. Capacitance follows from

    C = 2 P t / (V_nom^2 - V_cut^2)

**Model statement.** Every stage draws constant power behind a current
limit, and refills its store from whatever headroom the limit leaves. How
long a store lasts under a sag is

    store lasts = hold-up time / (demand - voltage x current limit)

The tests check simulated trip times against that arithmetic rather than
against recorded output.

**Model statement.** The model reports which element gave up first,
separately from the grader's verdict. The grader says which obligation
failed. The model says what inside the building failed.

---

## 8. What this is not

This is an averaged model. It carries energy and power at the millisecond
scale. It does not resolve point-on-wave switching, harmonics, phase
imbalance or sub-cycle protection behaviour. For a question that lives
between ten milliseconds and a few seconds, that is the right resolution.
For anything faster it is the wrong tool.

It does not perform converter model validation against hardware.

It does not issue compliance approval. It produces evidence.

The archetypes are configurations, not sites. Nothing in this repository is
a measurement of any real facility.

---

Author: Yasha Khandelwal, yasha.khandelwal@tech4biz.io
