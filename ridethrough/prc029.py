"""NERC PRC-029-2 ride-through tables and constants, as data.

Transcribed from NERC Reliability Standard PRC-029-2, Frequency and Voltage
Ride-through Requirements for Inverter-Based Resources, adopted by the NERC
Board of Trustees on 18 August 2026. Attachment 1 gives the two voltage
tables and Attachment 2 the frequency table.

This module is data only. Nothing in this package grades an inverter-based
resource yet. `validate/check_prc029.py` asserts every row and every
constant here against the text of the standard in
`validate/src_prc_029_2.txt`.

The standard prints each voltage row as a threshold, for example "< 0.90".
The rows are stored here as bands, so that row covers 0.70 up to 0.90. That
is a reading, and it is set out in docs/PRC-029-2.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from .envelope import CONTINUOUS, NOT_REQUIRED

SOURCE = (
    "NERC Reliability Standard PRC-029-2, Frequency and Voltage Ride-through "
    "Requirements for Inverter-Based Resources, adopted by the NERC Board of "
    "Trustees on 18 August 2026"
)

MANDATORY = "mandatory operation region"
CONTINUOUS_REGION = "continuous operation region"
PERMISSIVE = "permissive operation region"
MAY_RIDE_THROUGH = "may ride-through zone"


@dataclass(frozen=True)
class Row:
    """One row of a PRC-029-2 table.

    `printed` is the condition as the standard prints it. `low` and `high`
    are the band the row is stored as, which covers [low, high) unless the
    inclusive flags say otherwise.

    minimum_time is the minimum ride-through time in seconds, CONTINUOUS
    where the table prints "Continuous", or NOT_REQUIRED where it prints
    "N/A" or "May trip". region is None where the table prints no region.
    """

    printed: str
    low: float
    high: float
    region: str | None
    minimum_time: float | None
    inclusive_low: bool = True
    inclusive_high: bool = False

    def contains(self, value: float) -> bool:
        above = value >= self.low if self.inclusive_low else value > self.low
        below = value <= self.high if self.inclusive_high else value < self.high
        return above and below


@dataclass(frozen=True)
class Table:
    name: str
    source: str
    quantity: str
    unit: str
    rows: tuple[Row, ...]

    def row_for(self, value: float) -> Row:
        for row in self.rows:
            if row.contains(value):
                return row
        raise ValueError(f"{value} {self.unit} falls in no row of {self.name}")

    def minimum_time(self, value: float) -> float | None:
        """Minimum ride-through time in seconds for a held value."""
        return self.row_for(value).minimum_time

    def region(self, value: float) -> str | None:
        return self.row_for(value).region


_INF = float("inf")

# Attachment 1, Table 1. Type 3 and type 4 wind, and hybrids that include
# wind, unless connected through a dedicated VSC-HVDC facility (item 1).
PRC029_TABLE_1_WIND = Table(
    name="PRC-029-2 Table 1, AC-connected wind",
    source=SOURCE + ", Attachment 1, Table 1",
    quantity="voltage",
    unit="pu",
    rows=(
        Row("> 1.20", 1.20, _INF, MAY_RIDE_THROUGH, NOT_REQUIRED,
            inclusive_low=False),
        Row("≥ 1.10", 1.10, 1.20, MANDATORY, 1.0, inclusive_high=True),
        Row("> 1.05", 1.05, 1.10, CONTINUOUS_REGION, 1800.0,
            inclusive_low=False),
        Row("≤ 1.05 and ≥ 0.90", 0.90, 1.05, CONTINUOUS_REGION, CONTINUOUS,
            inclusive_high=True),
        Row("< 0.90", 0.70, 0.90, MANDATORY, 3.00),
        Row("< 0.70", 0.50, 0.70, MANDATORY, 2.50),
        Row("< 0.50", 0.25, 0.50, MANDATORY, 1.20),
        Row("< 0.25", 0.10, 0.25, MANDATORY, 0.16),
        Row("< 0.10", 0.0, 0.10, PERMISSIVE, 0.16),
    ),
)

# Attachment 1, Table 2. Every other inverter-based resource, including
# resources behind a dedicated VSC-HVDC facility and PV and battery plants
# (item 2). The 1.10 row is printed "> 1.10" here and "≥ 1.10" in Table 1.
PRC029_TABLE_2_OTHER = Table(
    name="PRC-029-2 Table 2, all other inverter-based resources",
    source=SOURCE + ", Attachment 1, Table 2",
    quantity="voltage",
    unit="pu",
    rows=(
        Row("> 1.20", 1.20, _INF, MAY_RIDE_THROUGH, NOT_REQUIRED,
            inclusive_low=False),
        Row("> 1.10", 1.10, 1.20, MANDATORY, 1.0,
            inclusive_low=False, inclusive_high=True),
        Row("> 1.05", 1.05, 1.10, CONTINUOUS_REGION, 1800.0,
            inclusive_low=False, inclusive_high=True),
        Row("≤ 1.05 and ≥ 0.90", 0.90, 1.05, CONTINUOUS_REGION, CONTINUOUS,
            inclusive_high=True),
        Row("< 0.90", 0.70, 0.90, MANDATORY, 6.00),
        Row("< 0.70", 0.50, 0.70, MANDATORY, 3.00),
        Row("< 0.50", 0.25, 0.50, MANDATORY, 1.20),
        Row("< 0.25", 0.10, 0.25, MANDATORY, 0.32),
        Row("< 0.10", 0.0, 0.10, PERMISSIVE, 0.32),
    ),
)

# Attachment 2, Table 3. The table prints no region.
PRC029_TABLE_3_FREQUENCY = Table(
    name="PRC-029-2 Table 3, frequency",
    source=SOURCE + ", Attachment 2, Table 3",
    quantity="frequency",
    unit="Hz",
    rows=(
        Row("> 61.8", 61.8, _INF, None, NOT_REQUIRED, inclusive_low=False),
        Row("> 61.2", 61.2, 61.8, None, 299.0,
            inclusive_low=False, inclusive_high=True),
        Row("≤ 61.2 and ≥ 58.8", 58.8, 61.2, None, CONTINUOUS,
            inclusive_high=True),
        Row("< 58.8", 57.0, 58.8, None, 299.0),
        Row("< 57.0", 0.0, 57.0, None, NOT_REQUIRED),
    ),
)

# Applicability, Section 4.2.2: non-BES resources of this size and voltage.
PRC029_MIN_MVA = 20.0
PRC029_MIN_KV = 60.0

# R1: conditions under which ride-through is not required.
PRC029_PHASE_JUMP_DEGREES = 25.0
PRC029_VHZ_PU = 1.1
PRC029_VHZ_SECONDS = 45.0
PRC029_VHZ_HIGH_PU = 1.18
PRC029_VHZ_HIGH_SECONDS = 2.0

# R2: performance during a voltage excursion.
PRC029_PRIORITY_BELOW_PU = 0.95        # R2.1.3
PRC029_RESTART_CYCLES = 5              # R2.3.1
PRC029_RECOVERY_SECONDS = 1.0          # R2.5

# R3 and footnote 9: rate of change of frequency.
PRC029_ROCOF_HZ_PER_SECOND = 5.0
PRC029_ROCOF_MIN_PERIOD_SECONDS = 0.1

# Attachment 1, items 7 to 9: how voltage time is counted.
PRC029_VOLTAGE_WINDOW_SECONDS = 10.0
PRC029_MAX_DEVIATIONS = 4

# Attachment 2, item 5: how frequency time is counted.
PRC029_FREQUENCY_WINDOW_SECONDS = 600.0
