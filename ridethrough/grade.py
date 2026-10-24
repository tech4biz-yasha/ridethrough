"""Grade a facility's response to a voltage disturbance against a grid code.

Inputs are traces. This module does not model a facility. It judges one.

Interpretation note, stated openly because it is the one judgement call here:
a grid code band table gives, for each voltage band, a minimum ride-through
time. For a rectangular sag that reading is unambiguous. For an arbitrary
trace this module applies the usual envelope reading: the disturbance stays
inside the envelope if, for every band, the total time spent below that
band's upper edge does not exceed that band's minimum ride-through time.
This reading is ours and has not been confirmed by ERCOT.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .codes import CODES, ERCOT, GridCode
from .envelope import CONTINUOUS, ERCOT_VOLTAGE, Envelope, VoltageProfile

RIDES_THROUGH = "rides through"
TRIPS = "trips"
NOT_REQUIRED = "not required"
ERROR = "error"


@dataclass
class Trace:
    """A sampled signal. Zero-order hold between samples."""

    times: Sequence[float]
    values: Sequence[float]

    def __post_init__(self) -> None:
        if len(self.times) != len(self.values):
            raise ValueError("times and values must be the same length")
        if len(self.times) < 2:
            raise ValueError("a trace needs at least two samples")
        if any(b <= a for a, b in zip(self.times, self.times[1:], strict=False)):
            raise ValueError("times must be strictly increasing")

    def at(self, t: float) -> float:
        if t <= self.times[0]:
            return self.values[0]
        for i in range(len(self.times) - 1):
            if self.times[i] <= t < self.times[i + 1]:
                return self.values[i]
        return self.values[-1]

    def time_below(self, level: float) -> float:
        """Total seconds the signal is strictly below `level`."""
        total = 0.0
        for i in range(len(self.times) - 1):
            if self.values[i] < level:
                total += self.times[i + 1] - self.times[i]
        return total

    def time_above(self, level: float) -> float:
        total = 0.0
        for i in range(len(self.times) - 1):
            if self.values[i] > level:
                total += self.times[i + 1] - self.times[i]
        return total

    def first_time_at_or_above(self, level: float, after: float) -> float | None:
        for t, v in zip(self.times, self.values, strict=True):
            if t >= after and v >= level:
                return t
        return None

    def minimum(self) -> float:
        return min(self.values)

    def maximum(self) -> float:
        return max(self.values)


@dataclass
class Check:
    name: str
    passed: bool | None
    detail: str
    margin: float | None = None


@dataclass
class Result:
    verdict: str
    checks: list[Check] = field(default_factory=list)
    trip_driver: str | None = None
    required: bool | None = None
    code: str | None = None

    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.passed is False]


def _required_by_profile(
    voltage: Trace, profile: VoltageProfile
) -> tuple[bool | None, str]:
    """A voltage against time floor, measured from fault inception."""
    inception = next(
        (t for t, v in zip(voltage.times, voltage.values, strict=True)
         if v < profile.continuous_low),
        None,
    )
    if inception is None:
        if voltage.maximum() <= profile.continuous_high:
            return None, (
                "voltage never leaves the continuous operating range, so this "
                "run tests nothing"
            )
        return None, "overvoltage only, which this profile does not cover"

    # Samples are held between points, and the floor rises with time, so the
    # binding moment inside a held segment is its end, not its start.
    for i in range(len(voltage.times) - 1):
        end = voltage.times[i + 1]
        if end <= inception:
            continue
        held = voltage.values[i]
        floor = profile.floor_at(end - inception)
        if held < floor - 1e-9:
            return False, (
                f"voltage {held:.3f} pu at {end - inception:.3f} s after "
                f"inception is below the {floor:.3f} pu floor, so the "
                f"facility may disconnect"
            )
    return True, (
        f"disturbance stays on or above the floor throughout "
        f"(deepest {voltage.minimum():.3f} pu)"
    )


def excursions(voltage: Trace, low: float, high: float) -> list[Trace]:
    """Split a trace into the separate times it leaves the continuous range.

    A train of reclosing sags is several disturbances, not one long one.
    ERCOT Section 2.14(2)(6) is explicit that the facility must ride through
    each such condition, so each has to be measured against the envelope on
    its own. Summing the time below a level across a whole trace would call
    six short sags one long excursion and reach the wrong answer.
    """
    pieces: list[Trace] = []
    start: int | None = None
    for i, v in enumerate(voltage.values):
        outside = v < low or v > high
        if outside and start is None:
            start = i
        elif not outside and start is not None:
            pieces.append(
                Trace(
                    list(voltage.times[start : i + 1]),
                    list(voltage.values[start : i + 1]),
                )
            )
            start = None
    if start is not None and start < len(voltage.times) - 1:
        pieces.append(
            Trace(list(voltage.times[start:]), list(voltage.values[start:]))
        )
    return pieces


def _one_excursion_by_bands(
    voltage: Trace, envelope: Envelope
) -> tuple[bool | None, str]:
    deepest = voltage.minimum()

    for band in envelope.bands:
        if band.minimum_time in (None, CONTINUOUS):
            continue
        if band.high <= envelope.continuous_low:
            spent = voltage.time_below(band.high)
            if spent > band.minimum_time + 1e-12:
                return False, (
                    f"voltage spent {spent:.3f} s below {band.high:.2f} pu, "
                    f"beyond the {band.minimum_time:.2f} s allowed there"
                )
        elif band.low >= envelope.continuous_high:
            spent = voltage.time_above(band.low)
            if spent > band.minimum_time + 1e-12:
                return False, (
                    f"voltage spent {spent:.3f} s above {band.low:.2f} pu, "
                    f"beyond the {band.minimum_time:.2f} s allowed there"
                )

    band = envelope.band_for(deepest) if deepest < envelope.continuous_low else None
    if band is not None and band.minimum_time is None:
        return None, f"deepest voltage {deepest:.3f} pu is outside any required band"

    return True, (
        f"disturbance stays inside the envelope (deepest {deepest:.3f} pu)"
    )


def _required_by_bands(
    voltage: Trace, envelope: Envelope
) -> tuple[bool | None, str]:
    pieces = excursions(voltage, envelope.continuous_low, envelope.continuous_high)
    if not pieces:
        return None, (
            "voltage never leaves the continuous operating range, so this "
            "run tests nothing"
        )

    verdicts = [_one_excursion_by_bands(piece, envelope) for piece in pieces]
    for index, (required, reason) in enumerate(verdicts, start=1):
        if required is not True:
            where = f"excursion {index} of {len(pieces)}: " if len(pieces) > 1 else ""
            return required, where + reason

    if len(pieces) == 1:
        return True, verdicts[0][1]
    return True, (
        f"{len(pieces)} separate excursions, each inside the envelope "
        f"(deepest {voltage.minimum():.3f} pu)"
    )


def ride_through_required(
    voltage: Trace, envelope=ERCOT_VOLTAGE
) -> tuple[bool | None, str]:
    """Is the facility required to ride this disturbance through?

    Returns (required, reason). `required` is None when the code leaves it
    optional, which is not the same as a failure.
    """
    if isinstance(envelope, VoltageProfile):
        return _required_by_profile(voltage, envelope)
    return _required_by_bands(voltage, envelope)


def grade(
    voltage: Trace,
    connected: Trace,
    active_power: Trace,
    current: Trace,
    pre_disturbance_power: float,
    max_normal_current: float,
    code: GridCode = ERCOT,
) -> Result:
    """Grade one run against a grid code.

    connected is 1.0 while the facility is connected and 0.0 once it is not.
    active_power and current are in the same units as the two scalars.
    """
    if isinstance(code, str):
        code = CODES[code]
    envelope = code.voltage
    required, reason = ride_through_required(voltage, envelope)
    result = Result(verdict=ERROR, required=required, code=code.name)

    if required is None:
        result.checks.append(Check("envelope", None, reason))
        result.verdict = ERROR if "tests nothing" in reason else NOT_REQUIRED
        return result

    result.checks.append(Check("envelope", required or None, reason))
    if not required:
        result.verdict = NOT_REQUIRED
        return result

    # Obligation: stay connected.
    stayed = all(v >= 0.5 for v in connected.values)
    result.checks.append(
        Check(
            "stays connected",
            stayed,
            "connected throughout" if stayed else "disconnected during the event",
        )
    )

    # Obligation: current ceiling, where the code sets one.
    if code.current_limit_pu is None:
        result.checks.append(
            Check(
                "current ceiling",
                None,
                "this code sets no current ceiling"
                + (
                    "; current blocking is permitted"
                    if code.current_blocking_allowed
                    else ""
                ),
            )
        )
    else:
        ceiling = code.current_limit_pu * max_normal_current
        worst = 0.0
        for t, v in zip(voltage.times, voltage.values, strict=True):
            if not envelope.is_continuous(v):
                worst = max(worst, current.at(t))
        result.checks.append(
            Check(
                "current ceiling",
                worst <= ceiling + 1e-9,
                f"peak {worst:.3f} against a ceiling of {ceiling:.3f} "
                f"({code.current_limit_pu:.2f} x normal)",
                margin=ceiling - worst,
            )
        )

    first_low = next(
        (t for t, v in zip(voltage.times, voltage.values, strict=True)
         if v < code.recovery_voltage_pu),
        None,
    )

    # Obligation: keep drawing power through the sag, where the code says so.
    if code.keep_consuming_above_pu is not None and first_low is not None:
        floor = code.keep_consuming_above_pu
        starved = [
            t
            for t, v in zip(voltage.times, voltage.values, strict=True)
            if floor <= v < code.recovery_voltage_pu
            and active_power.at(t) <= 1e-9 * max(1.0, pre_disturbance_power)
        ]
        in_window = any(
            floor <= v < code.recovery_voltage_pu for v in voltage.values
        )
        if not in_window:
            result.checks.append(
                Check(
                    "keeps consuming",
                    None,
                    f"voltage never sits between {floor:.2f} and "
                    f"{code.recovery_voltage_pu:.2f} pu",
                )
            )
        else:
            result.checks.append(
                Check(
                    "keeps consuming",
                    not starved,
                    f"draws power throughout {floor:.2f} to "
                    f"{code.recovery_voltage_pu:.2f} pu"
                    if not starved
                    else f"stops drawing power at {starved[0]:.3f} s while "
                    f"voltage is above {floor:.2f} pu",
                )
            )

    # Obligation: recover to each checkpoint in time.
    recovered_at = (
        voltage.first_time_at_or_above(code.recovery_voltage_pu, after=first_low)
        if first_low is not None
        else None
    )
    if recovered_at is None:
        result.checks.append(
            Check(
                "power recovery",
                None,
                f"voltage never returns above {code.recovery_voltage_pu:.2f} pu",
            )
        )
    else:
        tolerance = code.recovery_tolerance_of_rated * pre_disturbance_power
        for point in code.recovery:
            target = point.fraction * pre_disturbance_power - tolerance
            back_at = active_power.first_time_at_or_above(target, after=recovered_at)
            label = (
                "power recovery"
                if len(code.recovery) == 1
                else f"power recovery to {point.fraction:.0%}"
            )
            if back_at is None:
                result.checks.append(
                    Check(
                        label,
                        False,
                        f"never returns to {point.fraction:.0%} of "
                        f"pre-disturbance power",
                    )
                )
                continue
            took = back_at - recovered_at
            result.checks.append(
                Check(
                    label,
                    took <= point.seconds + 1e-9,
                    f"back to {point.fraction:.0%} in {took:.3f} s against "
                    f"{point.seconds:.1f} s allowed",
                    margin=point.seconds - took,
                )
            )

        # Obligation: do not overshoot on the way back.
        for window, allowance in code.overshoot_limits:
            ceiling = pre_disturbance_power * (1.0 + allowance)
            peak = max(
                (
                    active_power.at(t)
                    for t in active_power.times
                    if recovered_at <= t <= recovered_at + window
                ),
                default=0.0,
            )
            window_text = (
                "after" if window == float("inf") else f"within {window:.0f} s"
            )
            result.checks.append(
                Check(
                    f"overshoot {window_text} recovery",
                    peak <= ceiling + 1e-9,
                    f"peak {peak / pre_disturbance_power:.3f} of pre-disturbance "
                    f"against {1.0 + allowance:.2f} allowed",
                    margin=ceiling - peak,
                )
            )

    failures = result.failed()
    if failures:
        result.verdict = TRIPS
        result.trip_driver = failures[0].name
    else:
        result.verdict = RIDES_THROUGH
    return result
