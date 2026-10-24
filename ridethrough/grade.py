"""Grade a facility's response to a disturbance against a grid code.

Inputs are traces. This module does not model a facility. It judges one.

`grade` handles voltage, ERCOT Section 2.15. `grade_frequency` handles
frequency, Section 2.6.4. They are separate because the rule is.

Two readings in here are ours rather than the rule's, and both are carried
as open questions on each code object rather than buried here. The first is
how a band table applies to an event that moves through several bands. The
second is whether a train of reclosing sags is one disturbance event or
several, which 2.15(3)(e)(i) and 2.15(7) both turn on.

A check carrying `counts=False` is reported without deciding the verdict.
That is how this module handles a clause whose application the rule leaves
unsettled, and the clause each one rests on is named in `Check.clause`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .codes import CODES, ERCOT, GridCode
from .envelope import (
    CONTINUOUS,
    ERCOT_RECOVERY_FRACTION,
    ERCOT_VOLTAGE,
    Envelope,
    VoltageProfile,
)

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

    def reaches_and_holds(
        self, level: float, after: float, by: float
    ) -> float | None:
        """When the signal reached `level` within the window and is still
        there at the end of it, or None.

        **Model statement.** The rule requires a facility to "return to at
        least 90% of its pre-disturbance consumption level" within a stated
        time. A level is not a transient. This method therefore asks two
        things: did the signal reach the level inside the window, and is it
        still at or above the level when the window closes.

        That reading matters. Without it, a UPS drawing full rated current
        for fifty milliseconds to rebuild its DC bus, while the IT load it
        serves is switched off, was read as the facility returning to 90% of
        its consumption. That is a false pass, and a false pass is the worst
        failure a conformance tool can have.
        """
        reached = None
        for t, v in zip(self.times, self.values, strict=True):
            if after <= t <= after + by and v >= level:
                reached = t
                break
        if reached is None:
            return None
        return reached if self.at(after + by) >= level else None

    def minimum(self) -> float:
        return min(self.values)

    def maximum(self) -> float:
        return max(self.values)


@dataclass
class Check:
    """One obligation, judged.

    `counts` is False for a check that is reported but does not decide the
    verdict, which is how this grader handles a clause whose application is
    genuinely unsettled in the rule. Reporting it and declining to score it
    is more honest than picking a reading and calling it compliance.
    """

    name: str
    passed: bool | None
    detail: str
    margin: float | None = None
    counts: bool = True
    clause: str = ""


@dataclass
class Result:
    verdict: str
    checks: list[Check] = field(default_factory=list)
    trip_driver: str | None = None
    required: bool | None = None
    code: str | None = None

    def failed(self) -> list[Check]:
        """Failures that decide the verdict."""
        return [c for c in self.checks if c.passed is False and c.counts]

    def reported(self) -> list[Check]:
        """Failures reported but not scored, because the rule is unsettled."""
        return [c for c in self.checks if c.passed is False and not c.counts]


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
    ERCOT Section 2.15(7) is explicit that the facility must ride through
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
        return None, (
            f"deepest value {deepest:.3f} {envelope.unit} is outside any "
            f"required band"
        )

    return True, (
        f"disturbance stays inside the envelope "
        f"(deepest {deepest:.3f} {envelope.unit})"
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
        f"(deepest {voltage.minimum():.3f} {envelope.unit})"
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


def _excursion_spans(
    voltage: Trace, low: float, high: float
) -> list[tuple[float, float]]:
    """(start, end) of each time the voltage leaves the continuous range."""
    spans = []
    begin = None
    for i in range(len(voltage.times) - 1):
        outside = voltage.values[i] < low or voltage.values[i] > high
        if outside and begin is None:
            begin = voltage.times[i]
        elif not outside and begin is not None:
            spans.append((begin, voltage.times[i]))
            begin = None
    if begin is not None:
        spans.append((begin, voltage.times[-1]))
    return spans


def grade(
    voltage: Trace,
    connected: Trace,
    active_power: Trace,
    current: Trace,
    pre_disturbance_power: float,
    max_normal_current: float,
    code: GridCode | str = ERCOT,
    *,
    pre_disturbance_cooling_power: float = 0.0,
    cooling_tripped: bool = False,
    transfer_scheme: bool = False,
) -> Result:
    """Grade one run against a grid code.

    `connected` is 1.0 while the facility is connected and 0.0 once it is
    not. `active_power` and `current` are in the same units as the scalars.

    `pre_disturbance_cooling_power` and `cooling_tripped` carry ERCOT
    2.15(3)(c): if cooling load trips for voltage below 0.35 pu, the
    pre-disturbance cooling load is subtracted from the total before the
    recovery obligation is judged.

    `transfer_scheme` declares that the facility implements a load-transfer
    or control stabilization scheme under 2.15(3)(e). It is a design fact and
    is never inferred from the trace, because inferring it would let a
    facility that dropped out unintentionally be graded against the clause
    written for one that did so by design.
    """
    if isinstance(code, str):
        code = CODES[code]
    envelope = code.voltage
    required, reason = ride_through_required(voltage, envelope)
    result = Result(verdict=ERROR, required=required, code=code.name)

    if required is None:
        result.checks.append(Check("envelope", None, reason, clause="Table A"))
        result.verdict = ERROR if "tests nothing" in reason else NOT_REQUIRED
        return result

    result.checks.append(
        Check("envelope", required or None, reason, clause="Table A")
    )
    if not required:
        result.verdict = NOT_REQUIRED
        return result

    spans = _excursion_spans(
        voltage, envelope.continuous_low, envelope.continuous_high
    )
    deepest = voltage.minimum()

    # --- stay connected -------------------------------------------------
    stayed = all(v >= 0.5 for v in connected.values)
    result.checks.append(
        Check(
            "stays connected",
            stayed,
            "connected throughout" if stayed else "disconnected during the event",
            clause="2.15(3)",
        )
    )

    # --- current ceiling -------------------------------------------------
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
                clause="2.15(3)(d)",
            )
        )

    # --- how long the overcurrent persisted ------------------------------
    # 2.15(3)(d) also caps the duration. Reported, not scored: 2.15(3)(b)
    # requires a facility to keep consuming for up to 2 seconds between 0.80
    # and 0.90 pu, and a constant power load there draws above normal current
    # for as long as the sag lasts. The two clauses appear to pull against
    # each other and the rule does not say which governs.
    if code.overcurrent_max_seconds is not None:
        over = 0.0
        for i in range(len(voltage.times) - 1):
            t = voltage.times[i]
            if not envelope.is_continuous(voltage.values[i]) and (
                current.at(t) > max_normal_current + 1e-9
            ):
                over += voltage.times[i + 1] - t
        result.checks.append(
            Check(
                "overcurrent duration",
                over <= code.overcurrent_max_seconds + 1e-9,
                f"drew above normal current for {over:.3f} s against "
                f"{code.overcurrent_max_seconds:.2f} s; reported only, see "
                f"open questions",
                margin=code.overcurrent_max_seconds - over,
                counts=False,
                clause="2.15(3)(d)",
            )
        )

    # --- overvoltage hold -------------------------------------------------
    if code.overvoltage_hold_seconds is not None:
        above = voltage.time_above(envelope.continuous_high)
        in_band = any(
            envelope.continuous_high < v <= 1.20 for v in voltage.values
        )
        if in_band and above < code.overvoltage_hold_seconds:
            target = pre_disturbance_power * 0.999
            held = all(
                active_power.at(t) >= target
                for t, v in zip(voltage.times, voltage.values, strict=True)
                if v > envelope.continuous_high
            )
            result.checks.append(
                Check(
                    "holds power through overvoltage",
                    held,
                    f"overvoltage lasted {above:.3f} s, under the "
                    f"{code.overvoltage_hold_seconds:.1f} s threshold, so "
                    f"pre-disturbance power must be held",
                    clause="2.15(3)(a)",
                )
            )

    # --- cooling subtraction ---------------------------------------------
    effective_pre = pre_disturbance_power
    if (
        code.cooling_exempt_below_pu is not None
        and cooling_tripped
        and deepest < code.cooling_exempt_below_pu
    ):
        effective_pre = pre_disturbance_power - pre_disturbance_cooling_power
        result.checks.append(
            Check(
                "cooling exemption",
                None,
                f"voltage reached {deepest:.3f} pu, below "
                f"{code.cooling_exempt_below_pu:.2f} pu, and cooling tripped, "
                f"so {pre_disturbance_cooling_power:,.0f} of cooling load is "
                f"subtracted from pre-disturbance consumption",
                clause="2.15(3) and 2.15(3)(c)",
            )
        )

    first_low = next(
        (t for t, v in zip(voltage.times, voltage.values, strict=True)
         if v < code.recovery_voltage_pu),
        None,
    )
    recovered_at = (
        voltage.first_time_at_or_above(code.recovery_voltage_pu, after=first_low)
        if first_low is not None
        else None
    )

    # --- keep drawing power through the sag -------------------------------
    relieved = (
        transfer_scheme
        and code.transfer is not None
        and code.transfer.relieves_keep_consuming
    )
    if code.keep_consuming_above_pu is not None and first_low is not None:
        floor = code.keep_consuming_above_pu
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
                    clause="2.15(3)(b) and (c)",
                )
            )
        elif relieved:
            result.checks.append(
                Check(
                    "keeps consuming",
                    None,
                    "relieved: the facility declares a load-transfer scheme "
                    "and this code invokes it as relief",
                    clause="2.15(3)(c)(ii)",
                )
            )
        else:
            starved = [
                t
                for t, v in zip(voltage.times, voltage.values, strict=True)
                if floor <= v < code.recovery_voltage_pu
                and active_power.at(t) <= 1e-9 * max(1.0, pre_disturbance_power)
            ]
            result.checks.append(
                Check(
                    "keeps consuming",
                    not starved,
                    f"draws power throughout {floor:.2f} to "
                    f"{code.recovery_voltage_pu:.2f} pu"
                    if not starved
                    else f"stops drawing power at {starved[0]:.3f} s while "
                    f"voltage is above {floor:.2f} pu",
                    clause="2.15(3)(b) and (c)",
                )
            )

    # --- recovery ----------------------------------------------------------
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
            target = point.fraction * effective_pre - tolerance
            back_at = active_power.reaches_and_holds(
                target, after=recovered_at, by=point.seconds
            )
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
                        clause="2.15(3)(b) and (c)",
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
                    clause="2.15(3)(b) and (c)",
                )
            )

        # --- the load-transfer route ------------------------------------
        if (
            transfer_scheme
            and code.transfer is not None
            and deepest < code.transfer.applies_below_pu
        ):
            tp = code.transfer
            target = tp.recovery_seconds
            fraction = code.recovery[0].fraction
            needed = fraction * effective_pre
            at_recovery = active_power.at(recovered_at)

            if at_recovery >= needed - 1e-9:
                # The facility never fell below the recovery fraction, so it
                # never transferred and the clause is satisfied trivially.
                started = reached = True
                detail = (
                    f"already at or above {fraction:.0%} of pre-disturbance "
                    f"power when voltage recovered, so no transfer occurred"
                )
                took = 0.0
            else:
                back_at = active_power.reaches_and_holds(
                    needed, after=recovered_at, by=target
                )
                rising_at = next(
                    (
                        t
                        for t in active_power.times
                        if t > recovered_at
                        and active_power.at(t) > at_recovery + 1e-9
                    ),
                    None,
                )
                started = (
                    rising_at is not None
                    and rising_at - recovered_at <= tp.start_seconds + 1e-9
                )
                reached = (
                    back_at is not None
                    and back_at - recovered_at <= target + 1e-9
                )
                took = (back_at - recovered_at) if back_at else float("inf")
                detail = (
                    "begins returning "
                    + (
                        f"{rising_at - recovered_at:.3f} s"
                        if rising_at
                        else "never"
                    )
                    + f" after recovery against {tp.start_seconds:.2f} s, and "
                    f"reaches {fraction:.0%} in "
                    + (f"{took:.3f} s" if back_at else "never")
                    + f" against {target:.2f} s"
                )

            result.checks.append(
                Check(
                    "transfer route",
                    started and reached,
                    detail,
                    margin=(target - took) if took != float("inf") else None,
                    counts=tp.relieves_keep_consuming,
                    clause="2.15(3)(e)",
                )
            )

    # --- six sags in ninety seconds ---------------------------------------
    if code.min_sags is not None and len(spans) >= 2:
        window = code.min_sags_window_seconds
        worst_count = 0
        for begin, _ in spans:
            worst_count = max(
                worst_count,
                sum(1 for s2, _ in spans if begin <= s2 <= begin + window),
            )
        if worst_count >= 2:
            survived = stayed
            result.checks.append(
                Check(
                    "survives repeated sags",
                    survived if worst_count >= code.min_sags else None,
                    f"{worst_count} excursions inside a {window:.0f} s window; "
                    f"the rule requires surviving at least {code.min_sags}"
                    + ("" if worst_count >= code.min_sags else ", so this run "
                       "does not reach the threshold"),
                    clause="2.15(7)",
                )
            )

    # --- overshoot ---------------------------------------------------------
    if recovered_at is not None:
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


def grade_frequency(
    frequency: Trace,
    connected: Trace,
    active_power: Trace,
    pre_disturbance_power: float,
    code: GridCode | str = ERCOT,
    *,
    transfer_scheme: bool = False,
) -> Result:
    """Grade a frequency disturbance against ERCOT Section 2.6.4.

    Separate from `grade` because the rule is separate: 2.6.4 and 2.15 are
    two sections with two tables and two sets of obligations, and a run
    exercises one or the other.

    This grades 2.6.4(3), the table; 2.6.4(5), which says a facility shall
    keep consuming current and "should" stay within 10% of its
    pre-disturbance active power; and 2.6.4(6), the frequency transfer
    route. The word "should" in (5) is why that check is reported and not
    scored: the rule does not make it mandatory.
    """
    if isinstance(code, str):
        code = CODES[code]
    envelope = code.frequency
    result = Result(verdict=ERROR, code=code.name)

    if envelope is None:
        result.checks.append(
            Check(
                "frequency envelope",
                None,
                f"{code.name} states no frequency ride-through requirement",
            )
        )
        return result

    required, reason = ride_through_required(frequency, envelope)
    result.required = required
    result.checks.append(
        Check("frequency envelope", required or None, reason, clause="2.6.4(3)")
    )
    if required is None:
        result.verdict = ERROR if "tests nothing" in reason else NOT_REQUIRED
        return result
    if not required:
        result.verdict = NOT_REQUIRED
        return result

    stayed = all(v >= 0.5 for v in connected.values)
    result.checks.append(
        Check(
            "stays connected",
            stayed,
            "connected throughout" if stayed else "disconnected during the event",
            clause="2.6.4(3)",
        )
    )

    outside = [
        t
        for t, f in zip(frequency.times, frequency.values, strict=True)
        if not envelope.is_continuous(f)
    ]

    # 2.6.4(5): shall keep consuming current, and should stay within 10%.
    drawing = all(
        active_power.at(t) > 1e-9 * max(1.0, pre_disturbance_power) for t in outside
    )
    result.checks.append(
        Check(
            "keeps consuming",
            drawing,
            "draws power throughout the deviation"
            if drawing
            else "stops drawing power during a deviation requiring ride-through",
            clause="2.6.4(5)",
        )
    )

    if code.frequency_power_band is not None and outside:
        band = code.frequency_power_band
        worst = min(
            (active_power.at(t) / pre_disturbance_power for t in outside),
            default=1.0,
        )
        result.checks.append(
            Check(
                "holds power within band",
                worst >= 1.0 - band - 1e-9,
                f"fell to {worst:.3f} of pre-disturbance power against a "
                f"{band:.0%} band; the rule says should, not shall, so this "
                f"is reported and not scored",
                margin=worst - (1.0 - band),
                counts=False,
                clause="2.6.4(5)",
            )
        )

    # 2.6.4(6): the frequency transfer route.
    if transfer_scheme and code.frequency_transfer_seconds is not None and outside:
        back_inside = frequency.first_time_at_or_above(
            envelope.continuous_low, after=outside[0]
        )
        if back_inside is None:
            result.checks.append(
                Check(
                    "frequency transfer route",
                    None,
                    "frequency never returns to the continuous range",
                    clause="2.6.4(6)",
                )
            )
        else:
            target = ERCOT_RECOVERY_FRACTION * pre_disturbance_power
            limit = code.frequency_transfer_seconds
            back_at = active_power.reaches_and_holds(
                target, after=back_inside, by=limit
            )
            took = (back_at - back_inside) if back_at else float("inf")
            result.checks.append(
                Check(
                    "frequency transfer route",
                    back_at is not None and took <= limit + 1e-9,
                    f"back to {ERCOT_RECOVERY_FRACTION:.0%} in "
                    + (f"{took:.3f} s" if back_at else "never")
                    + f" against {limit:.1f} s allowed",
                    margin=(limit - took) if back_at else None,
                    clause="2.6.4(6)",
                )
            )

    failures = result.failed()
    if failures:
        result.verdict = TRIPS
        result.trip_driver = failures[0].name
    else:
        result.verdict = RIDES_THROUGH
    return result
