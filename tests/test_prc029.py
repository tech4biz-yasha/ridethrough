"""NERC PRC-029-2 tables and constants, as data.

The values asserted here were read from the standard, Attachment 1 Tables 1
and 2 and Attachment 2 Table 3. `validate/check_prc029.py` checks the same
values against the text of the standard, and this file checks that script
runs clean.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from ridethrough import prc029 as P
from ridethrough.envelope import CONTINUOUS, NOT_REQUIRED

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "validate" / "check_prc029.py"
EXTRACT = ROOT / "validate" / "src_prc_029_2.txt"

WIND = P.PRC029_TABLE_1_WIND
OTHER = P.PRC029_TABLE_2_OTHER
FREQUENCY = P.PRC029_TABLE_3_FREQUENCY


def test_each_table_has_the_rows_the_standard_prints():
    assert [r.printed for r in WIND.rows] == [
        "> 1.20", "≥ 1.10", "> 1.05", "≤ 1.05 and ≥ 0.90",
        "< 0.90", "< 0.70", "< 0.50", "< 0.25", "< 0.10",
    ]
    assert [r.printed for r in OTHER.rows] == [
        "> 1.20", "> 1.10", "> 1.05", "≤ 1.05 and ≥ 0.90",
        "< 0.90", "< 0.70", "< 0.50", "< 0.25", "< 0.10",
    ]
    assert [r.printed for r in FREQUENCY.rows] == [
        "> 61.8", "> 61.2", "≤ 61.2 and ≥ 58.8", "< 58.8", "< 57.0",
    ]


@pytest.mark.parametrize("voltage, seconds, region", [
    (1.25, NOT_REQUIRED, P.MAY_RIDE_THROUGH),
    (1.20, 1.0, P.MANDATORY),
    (1.15, 1.0, P.MANDATORY),
    (1.08, 1800.0, P.CONTINUOUS_REGION),
    (1.05, CONTINUOUS, P.CONTINUOUS_REGION),
    (1.00, CONTINUOUS, P.CONTINUOUS_REGION),
    (0.90, CONTINUOUS, P.CONTINUOUS_REGION),
    (0.89, 3.00, P.MANDATORY),
    (0.70, 3.00, P.MANDATORY),
    (0.69, 2.50, P.MANDATORY),
    (0.50, 2.50, P.MANDATORY),
    (0.49, 1.20, P.MANDATORY),
    (0.25, 1.20, P.MANDATORY),
    (0.24, 0.16, P.MANDATORY),
    (0.10, 0.16, P.MANDATORY),
    (0.09, 0.16, P.PERMISSIVE),
    (0.00, 0.16, P.PERMISSIVE),
])
def test_table_1_wind(voltage, seconds, region):
    assert WIND.minimum_time(voltage) == seconds
    assert WIND.region(voltage) == region


@pytest.mark.parametrize("voltage, seconds, region", [
    (1.25, NOT_REQUIRED, P.MAY_RIDE_THROUGH),
    (1.20, 1.0, P.MANDATORY),
    (1.15, 1.0, P.MANDATORY),
    (1.08, 1800.0, P.CONTINUOUS_REGION),
    (1.05, CONTINUOUS, P.CONTINUOUS_REGION),
    (1.00, CONTINUOUS, P.CONTINUOUS_REGION),
    (0.90, CONTINUOUS, P.CONTINUOUS_REGION),
    (0.89, 6.00, P.MANDATORY),
    (0.70, 6.00, P.MANDATORY),
    (0.69, 3.00, P.MANDATORY),
    (0.50, 3.00, P.MANDATORY),
    (0.49, 1.20, P.MANDATORY),
    (0.25, 1.20, P.MANDATORY),
    (0.24, 0.32, P.MANDATORY),
    (0.10, 0.32, P.MANDATORY),
    (0.09, 0.32, P.PERMISSIVE),
    (0.00, 0.32, P.PERMISSIVE),
])
def test_table_2_all_other(voltage, seconds, region):
    assert OTHER.minimum_time(voltage) == seconds
    assert OTHER.region(voltage) == region


def test_the_two_tables_differ_at_exactly_1_10_as_printed():
    # Table 1 prints "≥ 1.10" for the 1.0 s row. Table 2 prints "> 1.10".
    assert WIND.row_for(1.10).printed == "≥ 1.10"
    assert WIND.minimum_time(1.10) == 1.0
    assert WIND.region(1.10) == P.MANDATORY
    assert OTHER.row_for(1.10).printed == "> 1.05"
    assert OTHER.minimum_time(1.10) == 1800.0
    assert OTHER.region(1.10) == P.CONTINUOUS_REGION


@pytest.mark.parametrize("hertz, seconds", [
    (62.0, NOT_REQUIRED),
    (61.8, 299.0),
    (61.5, 299.0),
    (61.2, CONTINUOUS),
    (60.0, CONTINUOUS),
    (58.8, CONTINUOUS),
    (58.7, 299.0),
    (57.0, 299.0),
    (56.9, NOT_REQUIRED),
])
def test_table_3_frequency(hertz, seconds):
    assert FREQUENCY.minimum_time(hertz) == seconds
    assert FREQUENCY.region(hertz) is None


@pytest.mark.parametrize("table, top", [
    (WIND, 2.0), (OTHER, 2.0), (FREQUENCY, 70.0),
])
def test_every_value_falls_in_exactly_one_row(table, top):
    steps = 4000
    for k in range(steps + 1):
        value = top * k / steps
        owners = [row for row in table.rows if row.contains(value)]
        assert len(owners) == 1, (table.name, value, [r.printed for r in owners])


def test_a_negative_value_falls_in_no_row():
    with pytest.raises(ValueError):
        OTHER.row_for(-0.01)


def test_the_constants():
    assert P.PRC029_MIN_MVA == 20.0
    assert P.PRC029_MIN_KV == 60.0
    assert P.PRC029_PHASE_JUMP_DEGREES == 25.0
    assert (P.PRC029_VHZ_PU, P.PRC029_VHZ_SECONDS) == (1.1, 45.0)
    assert (P.PRC029_VHZ_HIGH_PU, P.PRC029_VHZ_HIGH_SECONDS) == (1.18, 2.0)
    assert P.PRC029_PRIORITY_BELOW_PU == 0.95
    assert P.PRC029_RESTART_CYCLES == 5
    assert P.PRC029_RECOVERY_SECONDS == 1.0
    assert P.PRC029_ROCOF_HZ_PER_SECOND == 5.0
    assert P.PRC029_ROCOF_MIN_PERIOD_SECONDS == 0.1
    assert P.PRC029_VOLTAGE_WINDOW_SECONDS == 10.0
    assert P.PRC029_MAX_DEVIATIONS == 4
    assert P.PRC029_FREQUENCY_WINDOW_SECONDS == 600.0


def test_the_check_script_passes():
    r = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL PRC-029-2 ROWS AND CONSTANTS MATCH" in r.stdout
    assert "MISMATCH" not in r.stdout
    assert "FAIL" not in r.stdout
    assert r.stdout.count("  OK ") == 46 + 16


def load_script():
    spec = importlib.util.spec_from_file_location("check_prc029", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


def test_the_check_script_catches_a_wrong_row(monkeypatch):
    check = load_script()
    lines = check.source_lines(EXTRACT)
    assert check.check_tables(lines) is True
    rows = list(OTHER.rows)
    wrong = P.Row("< 0.90", 0.70, 0.90, P.MANDATORY, 6.5)
    rows[4] = wrong
    monkeypatch.setattr(check.P, "PRC029_TABLE_2_OTHER",
                        P.Table(OTHER.name, OTHER.source, OTHER.quantity,
                                OTHER.unit, tuple(rows)))
    assert check.check_tables(lines) is False


def test_the_check_script_catches_a_wrong_boundary(monkeypatch):
    check = load_script()
    lines = check.source_lines(EXTRACT)
    rows = list(WIND.rows)
    # Store Table 1's 1.10 row as "above 1.10" instead of "at or above".
    rows[1] = P.Row("≥ 1.10", 1.10, 1.20, P.MANDATORY, 1.0,
                    inclusive_low=False, inclusive_high=True)
    rows[2] = P.Row("> 1.05", 1.05, 1.10, P.CONTINUOUS_REGION, 1800.0,
                    inclusive_low=False, inclusive_high=True)
    monkeypatch.setattr(check.P, "PRC029_TABLE_1_WIND",
                        P.Table(WIND.name, WIND.source, WIND.quantity,
                                WIND.unit, tuple(rows)))
    assert check.check_tables(lines) is False


def test_the_extract_is_shipped_and_names_its_source():
    text = EXTRACT.read_text(encoding="utf-8")
    assert "PRC-029-2" in text
    digest = "6dc95162c40d62eec980757818aeca8e735002aeeb2bc4ce48d2430a7da67753"
    assert f"sha256 {digest}" in text
    check = load_script()
    assert len(check.source_lines(EXTRACT)) == 50


def test_extract_lines_are_looked_up_on_their_stated_page():
    check = load_script()
    lines = check.source_lines(EXTRACT)
    pages = [""] * 18
    for page, text in lines:
        pages[page - 1] += " " + text
    assert check.missing_from(lines, pages) == []
    pages[13] = ""
    gone = check.missing_from(lines, pages)
    assert gone and {page for page, _ in gone} == {14}
