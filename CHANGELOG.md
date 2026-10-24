# Changelog

> **Note on versions before 0.6.0.** Releases 0.1.0 through 0.5.0 were built
> from an ERCOT presentation of NOGRR282 given to the System Protection
> Working Group on 24 February 2026, which described a draft. The rule
> changed before approval. Rule values quoted in those entries below are
> recorded as they were at the time and several of them are wrong. The
> approved values are in 0.6.0 and in `validate/`.

## 0.6.0 (2026-10-24)

Rebuilt against the approved rule, and two false passes removed.

### The provenance problem

Versions 0.1.0 through 0.5.0 took their ERCOT values from a presentation
about NOGRR282, not from NOGRR282. Nineteen further sets of stakeholder
comments followed that presentation, from AEP, Tesla, Google, Vistra, TIEC,
the Data Center Coalition and others, and the rule changed before the PUCT
approved it on 9 July 2026.

Everything now comes from the published rule: **ERCOT Nodal Operating Guide
Section 2, file `02-080126.docx`, effective 1 August 2026**, Sections 2.6.4
and 2.15, with Nodal Protocols Section 2.1 as amended by NPRR1308 for the
definitions.

What was wrong:

| | before | approved rule |
| --- | --- | --- |
| section | 2.14 | 2.15 |
| defined term | Large Electronic Load | Large Computational Load |
| voltage measure | RMS positive sequence | RMS |
| 1.10 < V <= 1.20 | 2.0 s | 1.0 s |
| lowest two bands | 0.20 boundary | 0.35 boundary |
| current ceiling | 125% | 150%, and capped at 0.5 s |
| overvoltage window | 2 s | 1.0 s |
| frequency edges | 61.8 and 57.0 | 63.0 and 57.5 |

The earlier finding that the ceiling binds at 0.80 pu is void. At 150% it
binds at 0.667 pu.

### Two false passes

A false pass tells an operator they comply when they do not. Both of these
were in shipped code, and neither was caught by 162 tests. Both were found
by noticing a sweep was not monotonic in sag depth and refusing to accept
it.

- A power supply in undervoltage lockout was drawing rated current to refill
  its own store while the load it serves was switched off. That put a
  single-sample spike into the power trace at the moment voltage recovered,
  and the grader read the spike as a return to 90% of pre-disturbance
  consumption.
- A UPS rebuilding its DC bus drew full rated current for about fifty
  milliseconds while the IT load was still off. That is real power from the
  grid, so it was not a modelling error, but it is not the facility
  returning to its consumption level. Recovery now requires the facility to
  reach the level inside the window and still be at or above it when the
  window closes, because the rule says "level" and a level is not a
  transient.

### Obligations added

- Section 2.6.4 is now graded, by `grade_frequency`. The package previously
  shipped a frequency table and graded nothing against it, which is worse
  than not shipping the table.
- 2.15(3)(e), the load-transfer route: begin returning within 0.25 s, reach
  90% within 0.5 s. Declared in the facility description and never inferred
  from a trace, because a facility that dropped out unintentionally should
  not be graded against the clause written for one that did so by design.
- 2.15(3)(c)(ii) relief: the transfer route relieves the keep-consuming
  obligation only after 1 January 2028, because that is the only clause that
  invokes it.
- 2.15(3) cooling: cooling may trip below 0.35 pu for any duration, and
  tripped cooling is subtracted from pre-disturbance consumption when
  recovery is judged.
- 2.15(3)(a), the overvoltage hold, and 2.15(7), the six-sags-in-90-seconds
  floor.
- 2.15(3)(d)'s 0.5 second overcurrent cap is reported and not scored, because
  it appears to pull against 2.15(3)(b).

### Saying what is not graded

Seven clauses are now declared out of scope with a reason, carried on each
code object rather than only in a document. Four places where the rule does
not settle how it applies are carried as open questions and reported rather
than resolved.

### Checking the values against the source

`validate/` ships the two sections as plain text plus two scripts.
`check_tables.py` parses Table A out of the rule and asserts the package
returns the stated time at both edges of every band. `check_scalars.py`
asserts each constant against a quoted sentence and confirms the superseded
draft values are absent. Both run in CI.

### Other

- `recharge_limit_pu` on a stage, so a facility can state how fast it
  refills its store. The default is its current limit, which is the fastest
  a facility could and the worst case for any overshoot obligation. With
  that default a UPS breaches Energinet's 10% overshoot ceiling, which is a
  finding rather than a bug.
- 202 tests.

## 0.5.0 (2026-10-24)

A bug fix that changes results, and the reclosing patterns that found it.

**The fix.** Until this release each stage drew only what the load demanded,
so an energy store that drained during a sag never refilled. A facility
therefore lost a little more of its store at every sag and collapsed after a
few, however much time passed in between. A real rectifier draws above the
load after a sag to rebuild its bus, which is what lets a facility survive a
second sag at all. Both stages now refill, bounded by the current limit.

Single-sag results are unchanged, because during a sag there is no headroom
to refill with. Every multi-sag result before 0.5.0 was wrong, and the
`ups` archetype under a train of sags was wrong in the direction of failing
when it should not have.

104 tests passed over this bug. None of them measured what happened between
two disturbances. `tests/test_recharge.py` now does.

**New.**

- `reclosing_sequence(depth, duration, times)` places sags at given times,
  because a recloser does not fire at a fixed interval.
- `dominion_july_2024()` builds the sag pattern reported for the 10 July 2024
  Dominion event: 0.683 pu, 75 ms, six sags, reclosing at 20 and 80 seconds.
  Transcribed from Dominion Energy, "An Overview of Data Centers Response to
  the Recent Large Load Events in Dominion Energy", Narges Ghiasi and
  Francisco A Zelaya, presented to the ERCOT Large Load Working Group on
  15 October 2026. The deck gives the count, magnitude, duration and
  reclosing delays. It does not give the individual sag timestamps, so their
  placement is ours.
- `ridethrough reclosing` runs every archetype against that pattern.
- 116 tests.

**Two things the pattern showed, both pinned as tests.**

At 0.683 pu for 75 ms, stored energy is not the failure mechanism. The sag is
too shallow and too short to drain a UPS bus that refills between shots. A
facility that fails this pattern fails on something else.

What it fails on instead is either a current limit above the 125% ceiling, or
a scheme that counts sags. The published pattern puts four sags inside one
minute and two more well outside it, so a counter set at four trips on the
fourth sag and a counter set at five never trips at all. Where the window
falls decides the outcome.

Neither of these reproduces the behaviour of any named facility, and nothing
in this repository is a measurement.

## 0.4.0 (2026-10-24)

The release shape. An operator can now grade their own site without editing
Python, and put the check in their CI.

- `ridethrough check <facility.json>` grades a facility description against
  every corner of a code and names what gave up at each one. Only `name`,
  `rated_power_mw` and `psu` are required.
- `ridethrough/spec.py` builds the model from JSON. Everything is stated the
  way a facility can state it: hold-up time in milliseconds, current limit as
  a multiple of normal, battery in minutes.
- `ridethrough run` writes a scorecard per code plus an index, in one command.
- `action.yml`: a GitHub Action, so `uses: tech4biz-yasha/ridethrough@main`
  grades a facility in CI and fails the step on a trip.
- A "Submit a facility" issue template, so an outside operator can have a
  design graded without opening a pull request. The shape, verdicts and trip
  drivers are published; site name, location and operator are not unless
  asked for.
- `docs/METHOD.md`: the method, with every statement marked as either a code
  statement tied to a named section or a model statement tied to a named file.
- `examples/facility-example.json`.
- 104 tests.

## 0.3.0 (2026-10-24)
A second grid code, so the tool is no longer about one market, and the two
obligations the earlier versions left out.

- `ridethrough/codes.py`: a grid code is now an object, an envelope plus the
  obligations that go with it. Three are shipped: ERCOT NOGRR282, ERCOT after
  1 January 2028, and Energinet TR 3.4.3.
- Energinet TR 3.4.3 UV-FRT, transcribed from Section 11(2) Table 2 of the
  regulation itself: 0 pu permitted to 0.15 s, 0.35 pu held to 0.55 s, then a
  ramp to 0.90 pu at 1.5 s. `VoltageProfile` handles an envelope given as a
  floor against time rather than as a table of bands.
- Energinet post-fault active power recovery from Section 12(2): 80% within
  5 s, 90% within 20 s, 95% within 30 s, with the 2% of rated power tolerance,
  plus the overshoot ceilings from Section 12(2)(d).
- ERCOT's keep-consuming obligation from Section 2.14(2)(b) and (c), with the
  floor at 0.80 pu now and 0.50 pu for facilities qualifying after
  1 January 2028 under Section 2.14(2)(c)(ii).
- Sweep points are now derived from whichever envelope is in play rather than
  chosen by hand. Each is a flat sag held for exactly as long as that code
  allows at that depth.
- `ridethrough repeated` runs a train of sags. `ridethrough codes` prints what
  each code requires and where it came from.
- `--code` on grade, simulate and sweep.
- `results/` now holds one scorecard per code.
- 86 tests.

One correction to 0.2.0, found by building the repeated-sag case:

- The envelope check summed time below a level across the whole trace, which
  called six separate 60 ms sags one 360 ms excursion and wrongly concluded
  the facility was not required to ride them through. ERCOT Section
  2.14(2)(6) is explicit that the facility must ride through each such
  condition. The trace is now split into separate excursions and each is
  measured on its own. Both the bug and the fix are pinned as tests.

One finding, pinned as a test:

- The northern Virginia failure mode reproduces. A facility with a scheme
  that transfers after four sags in a minute passes every single-sag test in
  the sweep and fails a reclosing train, tripping on the fourth sag. That is
  the behaviour ERCOT Section 2.14(2)(6) now forbids.

One structural difference between the codes, worth stating because it changes
what a facility has to prove:

- ERCOT caps current at 125% of maximum normal current during a disturbance.
  Energinet Section 11(2) explicitly permits current blocking under UV-FRT and
  sets no ceiling. A facility that satisfies one on current has told you
  nothing about the other.

Known limits in 0.3.0:

- Averaged model. It carries energy and power at the millisecond scale and
  does not resolve point-on-wave switching, harmonics, phase imbalance or
  sub-cycle protection behaviour.
- Archetypes are configurations, not sites. Nothing here is a measurement.
- No converter model validation against hardware.
- The ERCOT envelope reading for non-rectangular traces is ours and has not
  been confirmed by ERCOT.
- Energinet's LFSM-U requirement in Section 13 and the phase jump requirement
  in Section 9 are not graded.

## 0.2.0 (2026-10-24)

The facility model. Runs now come from physics instead of being written by
hand.

- `ridethrough/facility.py`: an averaged energy-reservoir model of the chain
  from grid, through an optional UPS, to the server power supplies and the IT
  load, with cooling on a thermal lag. Each store is specified by its hold-up
  time at rated power, not its capacitance, because hold-up is what a facility
  can actually state. Every stage draws constant power behind a current limit.
- Four physical trip drivers reported separately from the grader's verdict:
  server PSU undervoltage lockout, UPS DC bus collapse, battery depleted, and
  undervoltage protection trip.
- `ridethrough/archetypes.py`: five configurations, with the provenance of
  every default written down in the module docstring.
- `ridethrough simulate <archetype>` models a sag and grades it, optionally
  writing the run file.
- `ridethrough sweep` runs every archetype against seven points that each sit
  exactly on an ERCOT Table A band boundary, and writes the table.
- `ridethrough grade` is now explicit, and a bare path still works.
- `results/scorecard.json` holds the generated table.
- 63 tests. The facility tests check simulated trip times against closed-form
  hold-up arithmetic rather than against recorded output.

Two findings the model produced, both pinned as tests:

- A facility whose converter current limit sits below 1.25 pu can never fail
  the ERCOT current obligation at any sag depth. It runs out of stored energy
  instead. Where a facility fails depends on its current limit, not only on
  its stored energy.
- A constant power load draws 1/V, so the 125% ceiling binds at exactly
  0.80 pu. That matches ERCOT's own note on the same slide, which says 125%
  allows constant power for sags down to 0.8 pu.

Known limits in 0.2.0:

- Averaged model. It carries energy and power at the millisecond scale and
  does not resolve point-on-wave switching, harmonics, phase imbalance or
  sub-cycle protection behaviour.
- Archetypes are configurations, not sites. Nothing here is a measurement.
- No converter model validation against hardware.
- Does not cover the proportional-reduction requirement of Section
  2.14(2)(c)(i) and (ii) as a graded obligation, only as facility behaviour.
- Does not cover the repeated-sag requirement of Section 2.14(2)(6).
- The envelope reading for non-rectangular traces is ours and has not been
  confirmed by ERCOT.

## 0.1.0 (2026-10-24)

First release. The grader.

- ERCOT NOGRR282 voltage and frequency ride-through tables transcribed as
  data from ERCOT's SPWG presentation of 24 February 2026, Sections 2.6.4
  and 2.14, Table A.
- Grader for three obligations: stays connected, current ceiling at 125% of
  maximum normal current, and return to 90% of pre-disturbance consumption
  within 2 seconds of voltage recovery above 0.90 pu.
- Four verdicts: rides through, trips, not required, error. A run that tests
  nothing returns error and never a silent pass.
- Command line entry point reading a run from JSON.
- 34 tests pinning every row of both tables, the band edges, and the grader.
