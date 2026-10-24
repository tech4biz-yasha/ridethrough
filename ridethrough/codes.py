"""Grid codes, as objects.

A code is an envelope plus the obligations that go with it.

Every ERCOT value here is transcribed from the published rule, not from a
presentation about it: ERCOT Nodal Operating Guide Section 2, file
02-080126.docx, effective 1 August 2026, Sections 2.6.4 and 2.15, plus the
definitions added to Nodal Protocols Section 2.1 by NPRR1308. Both were
approved by the PUCT on 9 July 2026 in Project No. 54445.

That provenance matters. Earlier versions of this file were built from an
ERCOT presentation given to SPWG in February 2026, which described a draft.
Nineteen further sets of stakeholder comments followed it and the rule
changed substantially before approval. A presentation about a rule is not
the rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .envelope import (
    ENERGINET_UV_FRT,
    ERCOT_COOLING_EXEMPT_BELOW_PU,
    ERCOT_CURRENT_LIMIT,
    ERCOT_FREQUENCY,
    ERCOT_FREQUENCY_POWER_BAND,
    ERCOT_FREQUENCY_TRANSFER_SECONDS,
    ERCOT_HIGH_VOLTAGE_TRIP_PU,
    ERCOT_HIGH_VOLTAGE_TRIP_SECONDS,
    ERCOT_MIN_SAGS,
    ERCOT_MIN_SAGS_WINDOW_SECONDS,
    ERCOT_OVERCURRENT_MAX_SECONDS,
    ERCOT_OVERVOLTAGE_SECONDS,
    ERCOT_TRANSFER_RECOVERY_SECONDS,
    ERCOT_TRANSFER_START_SECONDS,
    ERCOT_VOLTAGE,
    Envelope,
    VoltageProfile,
)

AnyEnvelope = Envelope | VoltageProfile

ERCOT_SOURCE = (
    "ERCOT Nodal Operating Guide Section 2, file 02-080126.docx, effective "
    "1 August 2026, Sections 2.6.4 and 2.15"
)
ENERGINET_SOURCE = (
    "Energinet, Technical Regulation 3.4.3, Requirements for "
    "Transmission-Connected Demand Facilities, Revision 1, effective "
    "1 November 2024, Sections 11 and 12"
)


@dataclass(frozen=True)
class RecoveryPoint:
    """By `seconds` after recovery, consume at least `fraction` of before."""

    seconds: float
    fraction: float


@dataclass(frozen=True)
class TransferPath:
    """An alternative recovery route for a facility that transfers load.

    ERCOT Section 2.15(3)(e). A facility that implements a load-transfer or
    control stabilization scheme begins returning within `start_seconds` of
    voltage recovering above the recovery voltage, and reaches the recovery
    fraction within `recovery_seconds`. Both are tighter than the general
    route, so this is a constraint before it is a permission.

    `applies_below_pu` is the voltage below which the clause bites. 2.15(3)(e)
    opens "For undervoltage deviations below 0.8 p.u.", so it has no bearing
    on the 0.80 to 0.90 band, which 2.15(3)(b) governs.

    `relieves_keep_consuming` records whether this code's text invokes the
    transfer path as relief from the obligation to keep drawing power. Only
    2.15(3)(c)(ii), the rule for facilities qualifying after 1 January 2028,
    does so. The pre-2028 rule at 2.15(3)(c)(i) never mentions it and carries
    its own "if capable" escape instead.

    `actions_per_device_per_event` is 2.15(3)(e)(i): one load-transfer or
    control action per disturbance event per individual device.
    """

    start_seconds: float
    recovery_seconds: float
    applies_below_pu: float
    relieves_keep_consuming: bool
    actions_per_device_per_event: int = 1


@dataclass(frozen=True)
class GridCode:
    name: str
    source: str
    voltage: AnyEnvelope
    recovery: tuple[RecoveryPoint, ...]
    recovery_voltage_pu: float
    frequency: Envelope | None = None

    # Current ceiling as a multiple of maximum normal current, and how long
    # the overcurrent may persist. ERCOT 2.15(3)(d).
    current_limit_pu: float | None = None
    overcurrent_max_seconds: float | None = None
    current_blocking_allowed: bool = False

    # Voltage at or above which the facility must keep drawing some power.
    keep_consuming_above_pu: float | None = None

    # The load-transfer route, where the code offers one.
    transfer: TransferPath | None = None

    # Cooling or mechanical load may trip below this voltage for any
    # duration, and tripped cooling is subtracted from pre-disturbance
    # consumption when judging recovery. ERCOT 2.15(3) and 2.15(3)(c).
    cooling_exempt_below_pu: float | None = None

    # Overvoltage above the continuous range for less than this many seconds
    # requires consumption at the pre-disturbance level. ERCOT 2.15(3)(a).
    overvoltage_hold_seconds: float | None = None

    # A facility may trip above this voltage if it persists this long.
    # ERCOT 2.15(3)(f), which expires on 1 January 2028.
    high_voltage_trip_pu: float | None = None
    high_voltage_trip_seconds: float | None = None

    # A facility forced to use a counting scheme must survive at least this
    # many sags within this window. ERCOT 2.15(7).
    min_sags: int | None = None
    min_sags_window_seconds: float | None = None
    forbids_sag_counting: bool = False

    # Tolerance on recovery, as a fraction of rated power.
    recovery_tolerance_of_rated: float = 0.0
    # Overshoot ceiling after recovery, as (seconds, fraction of rated).
    overshoot_limits: tuple[tuple[float, float], ...] = ()

    # 2.6.4(5): "should" consume within this fraction of pre-disturbance
    # power during a frequency deviation. Reported, not scored.
    frequency_power_band: float | None = None
    # 2.6.4(6): a frequency transfer scheme returns to the recovery fraction
    # within this many seconds.
    frequency_transfer_seconds: float | None = None

    notes: str = ""
    open_questions: tuple[str, ...] = field(default_factory=tuple)
    # Clauses deliberately not graded, each with the reason.
    out_of_scope: tuple[tuple[str, str], ...] = field(default_factory=tuple)


ERCOT_OPEN_QUESTIONS = (
    "Table A gives a minimum ride-through time per voltage band. For a flat "
    "sag that is unambiguous. For an event that moves through several bands "
    "it needs a reading, and the one used here is ours.",
    "2.15(3)(e)(i) permits one load-transfer action per disturbance event "
    "per device, and 2.15(7) requires surviving six sags in 90 seconds. "
    "Whether a reclosing train is one disturbance event or several decides "
    "whether a transfer-based design can satisfy both. The rule does not say.",
    "2.15(3)(d) caps the allowable overcurrent at a duration not to exceed "
    "0.5 seconds, while 2.15(3)(b) requires a facility to keep consuming for "
    "up to 2 seconds between 0.80 and 0.90 pu. A constant power load in that "
    "band draws above normal current for as long as the sag lasts, so the "
    "two clauses appear to pull against each other.",
    "Whether 2.15(3)(e) binds a facility that has a transfer scheme before "
    "1 January 2028, or whether such a facility may rely on the two-second "
    "route in 2.15(3)(c), is not settled by the text. Both are reported.",
)

# Clauses this package does not grade, and why. Listing them is the point:
# a conformance tool that is silent about what it skips is worse than one
# that grades less and says so.
ERCOT_OUT_OF_SCOPE = (
    (
        "2.15(3)(c)(i)",
        "Reduction below 0.80 pu shall be proportional to the voltage drop "
        '"if capable". The escape clause makes the shape of the reduction '
        "unenforceable from a trace alone, because a trace cannot show what "
        "the equipment was capable of.",
    ),
    (
        "2.15(3)(e)(i)",
        "One load-transfer or control action per disturbance event per "
        "individual device. This package models a facility, not its "
        "individual devices, so it cannot count per-device actions.",
    ),
    (
        "2.15(1), 2.15(2), 2.6.4(1), 2.6.4(2)",
        "Exemption criteria, which turn on interconnection agreements, "
        "dates and written attestations rather than on how a facility "
        "behaves.",
    ),
    (
        "2.15(5), 2.15(6), 2.6.4(7), 2.6.4(8)",
        "Protection system settings, including the one-cycle minimum "
        "measurement window. These are design requirements on equipment "
        "settings, and this package grades outcomes rather than settings.",
    ),
    (
        "2.15(8), 2.6.4(9)",
        "The investigation and remediation process that follows a failure.",
    ),
    (
        "2.15(3)(f)",
        "Before 1 January 2028 a facility may trip for voltage above "
        "1.08 pu persisting 5 seconds or more. That band, 1.08 to 1.10 pu, "
        "lies inside the continuous operating range, so a run that "
        "exercises it never leaves the envelope and this package treats "
        "such a run as testing nothing. Grading the clause would mean "
        "reworking that, for a permission which expires in 2028.",
    ),
    (
        "2.6.4(3)",
        "The UFLS and Ancillary Service carve-out, which depends on "
        "obligations held outside the facility.",
    ),
)

ERCOT_TRANSFER_PRE_2028 = TransferPath(
    start_seconds=ERCOT_TRANSFER_START_SECONDS,
    recovery_seconds=ERCOT_TRANSFER_RECOVERY_SECONDS,
    applies_below_pu=0.80,
    relieves_keep_consuming=False,
)

ERCOT_TRANSFER_POST_2028 = TransferPath(
    start_seconds=ERCOT_TRANSFER_START_SECONDS,
    recovery_seconds=ERCOT_TRANSFER_RECOVERY_SECONDS,
    applies_below_pu=0.80,
    relieves_keep_consuming=True,
)

_ERCOT_COMMON = {
    "voltage": ERCOT_VOLTAGE,
    "frequency": ERCOT_FREQUENCY,
    "recovery": (RecoveryPoint(seconds=2.0, fraction=0.90),),
    "recovery_voltage_pu": 0.90,
    "current_limit_pu": ERCOT_CURRENT_LIMIT,
    "overcurrent_max_seconds": ERCOT_OVERCURRENT_MAX_SECONDS,
    "cooling_exempt_below_pu": ERCOT_COOLING_EXEMPT_BELOW_PU,
    "overvoltage_hold_seconds": ERCOT_OVERVOLTAGE_SECONDS,
    "min_sags": ERCOT_MIN_SAGS,
    "min_sags_window_seconds": ERCOT_MIN_SAGS_WINDOW_SECONDS,
    "forbids_sag_counting": True,
    "frequency_power_band": ERCOT_FREQUENCY_POWER_BAND,
    "frequency_transfer_seconds": ERCOT_FREQUENCY_TRANSFER_SECONDS,
    "open_questions": ERCOT_OPEN_QUESTIONS,
    "out_of_scope": ERCOT_OUT_OF_SCOPE,
}

# ERCOT for facilities qualifying after 14 November 2025 and on or before
# 1 January 2028. Section 2.15(3)(c)(i) asks for proportional reduction
# between 0.80 and 0.50 pu "if capable", so the hard floor for continuing to
# consume is 0.80 pu. Section 2.15(3)(f) is live in this period.
ERCOT = GridCode(
    name="ERCOT NOGRR282",
    source=ERCOT_SOURCE + ", with 2.15(3)(c)(i)",
    keep_consuming_above_pu=0.80,
    transfer=ERCOT_TRANSFER_PRE_2028,
    high_voltage_trip_pu=ERCOT_HIGH_VOLTAGE_TRIP_PU,
    high_voltage_trip_seconds=ERCOT_HIGH_VOLTAGE_TRIP_SECONDS,
    notes=(
        "2.15(3)(c)(i) applies. Reduction between 0.80 and 0.50 pu shall be "
        "proportional to the voltage drop if capable, and a facility whose "
        "equipment is not capable may reduce as much as necessary to remain "
        "connected. 2.15(3)(e) is not invoked as relief here."
    ),
    **_ERCOT_COMMON,
)

# ERCOT for facilities qualifying after 1 January 2028. Section
# 2.15(3)(c)(ii) requires continued consumption between 0.80 and 0.50 pu and
# is the only place that invokes the transfer route as relief. Section
# 2.15(3)(f) has expired.
ERCOT_2028 = GridCode(
    name="ERCOT NOGRR282, after 1 January 2028",
    source=ERCOT_SOURCE + ", with 2.15(3)(c)(ii)",
    keep_consuming_above_pu=0.50,
    transfer=ERCOT_TRANSFER_POST_2028,
    high_voltage_trip_pu=None,
    high_voltage_trip_seconds=None,
    notes=(
        "2.15(3)(c)(ii) applies. The facility shall continue consuming "
        "between 0.80 and 0.50 pu. A facility that cannot may implement a "
        "load-transfer scheme in accordance with 2.15(3)(e). The 2.15(3)(f) "
        "allowance to trip above 1.08 pu has expired."
    ),
    **_ERCOT_COMMON,
)

# Energinet TR 3.4.3. Transcribed from the regulation itself, so it was not
# affected by the ERCOT provenance problem described above.
ENERGINET = GridCode(
    name="Energinet TR 3.4.3",
    source=ENERGINET_SOURCE,
    voltage=ENERGINET_UV_FRT,
    frequency=None,
    recovery=(
        RecoveryPoint(seconds=5.0, fraction=0.80),
        RecoveryPoint(seconds=20.0, fraction=0.90),
        RecoveryPoint(seconds=30.0, fraction=0.95),
    ),
    recovery_voltage_pu=0.90,
    current_limit_pu=None,
    current_blocking_allowed=True,
    keep_consuming_above_pu=None,
    transfer=None,
    cooling_exempt_below_pu=None,
    recovery_tolerance_of_rated=0.02,
    overshoot_limits=((5.0, 0.10), (float("inf"), 0.05)),
    notes=(
        "Section 11(2) permits current blocking under UV-FRT, so no current "
        "ceiling applies. Recovery is staged over 30 seconds rather than 2."
    ),
)

CODES = {
    "ercot": ERCOT,
    "ercot-2028": ERCOT_2028,
    "energinet": ENERGINET,
}
