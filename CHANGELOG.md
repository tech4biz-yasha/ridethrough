# Changelog

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
