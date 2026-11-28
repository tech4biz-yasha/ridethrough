"""Two voltage events, each counted two ways against a band table.

    python examples/counting_cases.py

A band table gives a minimum ride-through time for each voltage band. That
settles a flat sag. It does not settle an event that moves through several
bands, or several sags close together. Each case below is counted two ways,
and the two ways disagree on whether the facility has to ride through.

The table is ERCOT Nodal Operating Guide Section 2.15(3), Table A, as this
package carries it. Nothing here adds a rule value or changes how the
package grades. The reading the package itself uses is marked in the output,
and its verdict is printed in its own words.
"""

import signal

from ridethrough import ERCOT_VOLTAGE, Trace, excursions, ride_through_required
from ridethrough.envelope import CONTINUOUS

TOLERANCE = 1e-12

# Case 1. One sag through two bands: 0.45 pu for 0.2 s, then 0.85 pu for
# 1.9 s, then back inside the continuous range.
MULTI_BAND = Trace(
    [0.0, 1.0, 1.2, 3.1, 5.0],
    [1.00, 0.45, 0.85, 1.00, 1.00],
)

# Case 2. Six sags to 0.85 pu, each 0.4 s. The spacing is ours: one sag
# every 15 s, so the last ends 75.4 s after the first begins.
SAG_COUNT = 6
SAG_DEPTH = 0.85
SAG_SECONDS = 0.4
SAG_EVERY = 15.0
WINDOW_SECONDS = 90.0


def six_sags() -> Trace:
    times = [0.0]
    values = [1.00]
    for k in range(SAG_COUNT):
        begin = 1.0 + k * SAG_EVERY
        times += [begin, begin + SAG_SECONDS]
        values += [SAG_DEPTH, 1.00]
    # A few quiet seconds after the last sag, so the trace ends at 80 s.
    times.append(times[-1] + 3.6)
    values.append(1.00)
    return Trace(times, values)


SIX_SAGS = six_sags()


def sag_bands(envelope=ERCOT_VOLTAGE):
    """The bands below the continuous range that carry a time, highest first."""
    return [
        band
        for band in envelope.bands
        if band.minimum_time not in (None, CONTINUOUS)
        and band.high <= envelope.continuous_low
    ]


def time_in_each_band(voltage: Trace, envelope=ERCOT_VOLTAGE):
    """Seconds spent inside each band, counted band by band."""
    return [
        (band, voltage.time_below(band.high) - voltage.time_below(band.low))
        for band in sag_bands(envelope)
    ]


def time_below_each_edge(voltage: Trace, envelope=ERCOT_VOLTAGE):
    """Seconds spent anywhere below each band's upper edge."""
    return [(band, voltage.time_below(band.high)) for band in sag_bands(envelope)]


def longest_below_each_edge(voltage: Trace, envelope=ERCOT_VOLTAGE):
    """The same count, taken on each excursion alone, keeping the longest."""
    pieces = excursions(voltage, envelope.continuous_low, envelope.continuous_high)
    return [
        (band, max(piece.time_below(band.high) for piece in pieces))
        for band in sag_bands(envelope)
    ]


def within(rows) -> bool:
    """True when no band's time is exceeded."""
    return all(spent <= band.minimum_time + TOLERANCE for band, spent in rows)


def _sentence(required: bool) -> str:
    if required:
        return "The facility must ride through."
    return "The facility is not required to ride through."


def _show(title: str, rows, label, required: bool, said: str = "") -> None:
    print(f"  {title}")
    for band, spent in rows:
        over = "   exceeded" if spent > band.minimum_time + TOLERANCE else ""
        print(
            f"    {label(band):<18s}{spent:6.3f} s against "
            f"{band.minimum_time:.2f} s allowed{over}"
        )
    print(f"    {_sentence(required)}")
    if said:
        print(f"    ridethrough: {said}")
    print()


def _inside(band) -> str:
    if band.low <= 0.0:
        return f"below {band.high:.2f} pu"
    return f"{band.low:.2f} to {band.high:.2f} pu"


def _below(band) -> str:
    return f"below {band.high:.2f} pu"


def main() -> int:
    print(f"table: {ERCOT_VOLTAGE.source}")
    print()

    print("Case 1. One sag through two bands")
    print("0.45 pu for 0.2 s, then 0.85 pu for 1.9 s")
    print()
    rows = time_in_each_band(MULTI_BAND)
    _show("Counted band by band", rows, _inside, within(rows))
    required, said = ride_through_required(MULTI_BAND, ERCOT_VOLTAGE)
    _show(
        "Counted as total time below each band's upper edge"
        " (what ridethrough does)",
        time_below_each_edge(MULTI_BAND),
        _below,
        bool(required),
        said,
    )

    print(f"Case 2. Six sags inside {WINDOW_SECONDS:.0f} seconds")
    print(
        f"{SAG_COUNT} sags to {SAG_DEPTH:.2f} pu, each {SAG_SECONDS:.1f} s, "
        f"one every {SAG_EVERY:.0f} s"
    )
    print()
    required, said = ride_through_required(SIX_SAGS, ERCOT_VOLTAGE)
    _show(
        "Each sag assessed on its own, longest shown (what ridethrough does)",
        longest_below_each_edge(SIX_SAGS),
        _below,
        bool(required),
        said,
    )
    rows = time_below_each_edge(SIX_SAGS)
    _show("Time added across all six sags", rows, _below, within(rows))
    return 0


if __name__ == "__main__":
    # Piping into head or less closes the pipe early. End quietly.
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    raise SystemExit(main())
