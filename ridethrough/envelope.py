"""Ride-through envelopes as data.

ERCOT values are transcribed from ERCOT's own presentation
"Large Electronic Load Ride-Through Requirements, NOGRR 282 and NPRR 1308",
Patrick Gravois, SPWG, 24 February 2026, Sections 2.6.4 and 2.14, Table A.

Nothing in this file is inferred. Every number appears in that document.
"""

from __future__ import annotations

from dataclasses import dataclass

CONTINUOUS = float("inf")
NOT_REQUIRED = None


@dataclass(frozen=True)
class Band:
    """One row of a grid code ride-through table.

    The band covers values in [low, high). `inclusive_high` makes the top
    edge closed instead, matching how the source table is written.

    minimum_time is the minimum ride-through time in seconds,
    CONTINUOUS for the continuous operating range,
    or NOT_REQUIRED where the code says "may ride through or trip".
    """

    low: float
    high: float
    minimum_time: float | None
    inclusive_low: bool = True
    inclusive_high: bool = False
    note: str = ""

    def contains(self, value: float) -> bool:
        above = value >= self.low if self.inclusive_low else value > self.low
        below = value <= self.high if self.inclusive_high else value < self.high
        return above and below


@dataclass(frozen=True)
class Envelope:
    name: str
    source: str
    quantity: str
    unit: str
    bands: tuple[Band, ...]
    continuous_low: float
    continuous_high: float

    def band_for(self, value: float) -> Band:
        for band in self.bands:
            if band.contains(value):
                return band
        raise ValueError(f"{value} {self.unit} falls in no band of {self.name}")

    def minimum_time(self, value: float) -> float | None:
        """Minimum ride-through time in seconds for a held value."""
        return self.band_for(value).minimum_time

    def is_continuous(self, value: float) -> bool:
        return self.continuous_low <= value <= self.continuous_high

    def corner_points(self) -> tuple[tuple[float, float], ...]:
        """Worst cases this envelope actually requires: each sag band held
        for exactly as long as the table allows it."""
        corners: list[tuple[float, float]] = []
        for band in self.bands:
            if band.minimum_time in (None, CONTINUOUS):
                continue
            if band.high <= self.continuous_low:
                corners.append((round(band.high - 0.05, 4), band.minimum_time))
                corners.append((round(band.low, 4), band.minimum_time))
        seen: set[tuple[float, float]] = set()
        unique: list[tuple[float, float]] = []
        for point in corners:
            if point not in seen:
                seen.add(point)
                unique.append(point)
        return tuple(sorted(unique, reverse=True))


# ERCOT Nodal Operating Guide Section 2.14(2), Table A.
ERCOT_VOLTAGE = Envelope(
    name="ERCOT NOGRR282 voltage",
    source=(
        "ERCOT, Large Electronic Load Ride-Through Requirements, "
        "NOGRR 282 and NPRR 1308, SPWG, 24 Feb 2026, Section 2.14(2) Table A"
    ),
    quantity="RMS positive sequence voltage",
    unit="pu",
    continuous_low=0.90,
    continuous_high=1.10,
    bands=(
        Band(1.20, float("inf"), NOT_REQUIRED, inclusive_low=False,
             note="May ride through or trip"),
        Band(1.10, 1.20, 2.0, inclusive_low=False, inclusive_high=True),
        Band(0.90, 1.10, CONTINUOUS, inclusive_high=True,
             note="Continuous operating range"),
        Band(0.80, 0.90, 2.0),
        Band(0.50, 0.80, 0.5),
        Band(0.20, 0.50, 0.25),
        Band(0.0, 0.20, 0.15),
    ),
)

# ERCOT Nodal Operating Guide Section 2.6.4(2), Table A.
ERCOT_FREQUENCY = Envelope(
    name="ERCOT NOGRR282 frequency",
    source=(
        "ERCOT, Large Electronic Load Ride-Through Requirements, "
        "NOGRR 282 and NPRR 1308, SPWG, 24 Feb 2026, Section 2.6.4(2) Table A"
    ),
    quantity="system frequency",
    unit="Hz",
    continuous_low=58.8,
    continuous_high=61.2,
    bands=(
        Band(61.8, float("inf"), NOT_REQUIRED, inclusive_low=False,
             note="May ride through or trip"),
        Band(61.2, 61.8, 299.0, inclusive_low=False, inclusive_high=True),
        Band(58.8, 61.2, CONTINUOUS, inclusive_high=True,
             note="Continuous operating range"),
        Band(57.0, 58.8, 299.0),
        Band(0.0, 57.0, NOT_REQUIRED,
             note="May ride through or trip"),
    ),
)

# Section 2.14(2)(d): current during a disturbance outside the continuous
# range shall not exceed this multiple of maximum normal current.
ERCOT_CURRENT_LIMIT = 1.25

# Sections 2.14(2)(b) and (c): active power must return to at least this
# fraction of pre-disturbance consumption, within this many seconds of
# voltage returning above 0.90 pu.
ERCOT_RECOVERY_FRACTION = 0.90
ERCOT_RECOVERY_SECONDS = 2.0

# Section 2.14(2): voltage above which the disturbance is considered cleared.
ERCOT_RECOVERY_VOLTAGE = 0.90


@dataclass(frozen=True)
class VoltageProfile:
    """A ride-through envelope given as a voltage against time curve.

    Some codes state the envelope as a floor that rises with time from the
    moment of the fault, rather than as a table of bands. The facility must
    stay connected while the retained voltage is on or above the floor.

    `points` are (seconds since fault inception, minimum voltage in pu),
    in order. Between points the floor is held at the earlier value until
    `ramped` says otherwise, in which case it is interpolated.
    """

    name: str
    source: str
    unit: str
    points: tuple[tuple[float, float], ...]
    continuous_low: float
    continuous_high: float
    ramped_from: float = float("inf")

    def floor_at(self, t: float) -> float:
        """The minimum voltage required at t seconds after fault inception."""
        if t < 0:
            return self.continuous_low
        last_t, last_v = self.points[0]
        for point_t, point_v in self.points:
            if t < point_t:
                if last_t >= self.ramped_from and point_t > last_t:
                    span = (t - last_t) / (point_t - last_t)
                    return last_v + span * (point_v - last_v)
                return last_v
            last_t, last_v = point_t, point_v
        return last_v

    def is_continuous(self, value: float) -> bool:
        return self.continuous_low <= value <= self.continuous_high

    def longest_hold_at(self, depth_pu: float, resolution: float = 1e-3) -> float:
        """How long a flat sag to `depth_pu` may be held and still sit on or
        above the floor. Found by walking the curve, not assumed."""
        t = 0.0
        last = self.points[-1][0]
        while t <= last:
            if self.floor_at(t) > depth_pu + 1e-12:
                return max(0.0, t - resolution)
            t += resolution
        return last

    def corner_points(self) -> tuple[tuple[float, float], ...]:
        """Worst cases this profile requires: each stated voltage held for as
        long as the floor allows it."""
        depths = sorted(
            {round(v, 4) for _, v in self.points if v < self.continuous_low}
            | {round(self.floor_at(1.0), 2)},
            reverse=True,
        )
        return tuple(
            (depth, round(self.longest_hold_at(depth), 3)) for depth in depths
        )


# Energinet Technical Regulation 3.4.3, Section 11(2), Table 2.
# Uret 0 pu at tclear 0.15 s; Uclear 0.35 pu at trec1 0.15 s;
# Urec1 0.35 pu at trec2 0.55 s; Urec2 0.90 pu at trec3 1.5 s.
ENERGINET_UV_FRT = VoltageProfile(
    name="Energinet TR 3.4.3 UV-FRT",
    source=(
        "Energinet, Technical Regulation 3.4.3, Requirements for "
        "Transmission-Connected Demand Facilities, Revision 1, effective "
        "1 November 2024, Section 11(2), Table 2"
    ),
    unit="pu",
    continuous_low=0.90,
    continuous_high=1.10,
    points=(
        (0.00, 0.00),
        (0.15, 0.35),
        (0.55, 0.35),
        (1.50, 0.90),
    ),
    ramped_from=0.55,
)
