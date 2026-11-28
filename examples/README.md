# Example runs

Each run file describes one run: what the grid voltage did, and what the
facility did in response. Grade one with:

    ridethrough examples/sag_065pu_400ms.json

These two are hand-written illustrations, not measurements. No facility was
measured to produce them. Measured runs will live under `results/` once the
facility model lands in 0.2.0.

## The two counting cases

With the package installed:

    python examples/counting_cases.py

Two voltage events, each counted two ways against a band table. In each
case one way of counting requires the facility to ride through and the other
does not.

Case 1 is one sag through two bands: 0.45 pu for 0.2 s, then 0.85 pu for
1.9 s. Counted band by band it stays inside every band's time. Counted as
total time below each band's upper edge it spends 2.1 s below 0.90 pu,
against the 2.0 s allowed there.

Case 2 is six sags to 0.85 pu, each 0.4 s, inside 90 seconds. Assessed one
at a time, each is inside the 2.0 s allowed. Added together they come to
2.4 s.

The output marks the reading this package uses in each case and prints the
package's own verdict next to it. The other reading is worked out in the
script, from the same table. Why the package reads the table the way it does
is in `docs/METHOD.md`, section 3.

These are the two cases in Tech4Biz's comments of 26 November 2026 on PJM's
filing on operational requirements for Large Computational Load, FERC Docket
No. ER27-522-000. The comments state them against PJM's draft Manual 14B,
Attachment D-2, Table 1, as presented to the PJM Planning Committee on
6 October 2026. That table is a draft and is not in this package, so the
script runs the same two events against ERCOT Section 2.15(3), Table A. From
0.35 pu upward that draft table gives the same times as ERCOT's, and neither
case goes below 0.45 pu, so the times and limits the comments quote are the
ones printed.

The comments give the count, depth and duration of the six sags and the
90 seconds. The spacing of one sag every 15 seconds is ours.
