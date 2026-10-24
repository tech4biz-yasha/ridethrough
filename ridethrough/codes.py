"""Grid codes, as objects.

A code is an envelope plus the obligations that go with it. The two codes
here share a structure and differ in their values, with one exception worth
pointing at: ERCOT caps the current a facility may draw during a disturbance,
and Energinet does the opposite, explicitly permitting current blocking
during undervoltage ride-through. A facility that satisfies one on current
has told you nothing about the other.

Every value is transcribed from the source named in each code. Nothing here
is inferred, and where a code says nothing about an obligation, that
obligation is None rather than a guess.
"""

from __future__ import annotations

from dataclasses import dataclass

from .envelope import (
    ENERGINET_UV_FRT,
    ERCOT_FREQUENCY,
    ERCOT_VOLTAGE,
    Envelope,
    VoltageProfile,
)

AnyEnvelope = Envelope | VoltageProfile


@dataclass(frozen=True)
class RecoveryPoint:
    """By `seconds` after recovery, consume at least `fraction` of before."""

    seconds: float
    fraction: float


@dataclass(frozen=True)
class GridCode:
    name: str
    source: str
    voltage: AnyEnvelope
    recovery: tuple[RecoveryPoint, ...]
    recovery_voltage_pu: float
    frequency: Envelope | None = None
    current_limit_pu: float | None = None
    current_blocking_allowed: bool = False
    # Voltage at or above which the facility must keep drawing some power.
    keep_consuming_above_pu: float | None = None
    # Tolerance on recovery, as a fraction of rated power.
    recovery_tolerance_of_rated: float = 0.0
    # Overshoot ceiling after recovery, as (seconds, fraction of rated).
    overshoot_limits: tuple[tuple[float, float], ...] = ()
    forbids_sag_counting: bool = False
    notes: str = ""


ERCOT_SOURCE = (
    "ERCOT, Large Electronic Load Ride-Through Requirements, NOGRR 282 and "
    "NPRR 1308, SPWG, 24 February 2026, Sections 2.6.4 and 2.14"
)

# ERCOT as it stands for facilities qualifying on or before 1 January 2028.
# Section 2.14(2)(b) requires the facility to keep consuming between 0.80 and
# 0.90 pu. Below 0.80, Section 2.14(2)(c)(i) allows reduction proportional to
# the voltage drop where capable, and as much as needed below 0.50 pu.
ERCOT = GridCode(
    name="ERCOT NOGRR282",
    source=ERCOT_SOURCE,
    voltage=ERCOT_VOLTAGE,
    frequency=ERCOT_FREQUENCY,
    recovery=(RecoveryPoint(seconds=2.0, fraction=0.90),),
    recovery_voltage_pu=0.90,
    current_limit_pu=1.25,
    keep_consuming_above_pu=0.80,
    forbids_sag_counting=True,
    notes=(
        "Section 2.14(2)(d) caps current at 125% of maximum normal current "
        "while outside the continuous range. Section 2.14(2)(6) forbids a "
        "scheme that trips on a count of sags the facility must ride through."
    ),
)

# ERCOT as it applies to facilities qualifying after 1 January 2028.
# Section 2.14(2)(c)(ii) moves the floor: the facility shall continue
# consuming between 0.80 and 0.50 pu, and may reduce as needed below 0.50.
ERCOT_2028 = GridCode(
    name="ERCOT NOGRR282, after 1 January 2028",
    source=ERCOT_SOURCE + ", Section 2.14(2)(c)(ii)",
    voltage=ERCOT_VOLTAGE,
    frequency=ERCOT_FREQUENCY,
    recovery=(RecoveryPoint(seconds=2.0, fraction=0.90),),
    recovery_voltage_pu=0.90,
    current_limit_pu=1.25,
    keep_consuming_above_pu=0.50,
    forbids_sag_counting=True,
    notes="Same as ERCOT, with the keep-consuming floor moved to 0.50 pu.",
)

# Energinet Technical Regulation 3.4.3, Revision 1, effective 1 Nov 2024.
# Section 11(2) permits current blocking during UV-FRT, so there is no
# current ceiling. Section 12(2) sets three recovery checkpoints with a 2%
# of rated power tolerance, and Section 12(2)(d) caps overshoot.
ENERGINET = GridCode(
    name="Energinet TR 3.4.3",
    source=(
        "Energinet, Technical Regulation 3.4.3, Requirements for "
        "Transmission-Connected Demand Facilities, Revision 1, effective "
        "1 November 2024, Sections 11 and 12"
    ),
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
