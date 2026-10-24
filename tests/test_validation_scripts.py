"""The validation scripts must pass, and the suite must say so.

These check the package against the published rule rather than against
itself. Keeping them in CI means a value cannot drift away from its source
without the build going red.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_script(name):
    return subprocess.run(
        [sys.executable, str(ROOT / "validate" / name)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_every_table_row_matches_the_source():
    r = run_script("check_tables.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL TABLE ROWS MATCH" in r.stdout
    assert "MISMATCH" not in r.stdout


def test_every_constant_is_justified_by_a_quoted_sentence():
    r = run_script("check_scalars.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL SCALARS JUSTIFIED" in r.stdout
    assert "FAIL" not in r.stdout


def test_the_source_extracts_are_shipped():
    for name in ("src_2_15.txt", "src_2_6_4.txt", "coverage.md", "README.md"):
        assert (ROOT / "validate" / name).exists()


def test_the_superseded_draft_values_are_absent_from_the_source():
    src = (ROOT / "validate" / "src_2_15.txt").read_text()
    src += (ROOT / "validate" / "src_2_6_4.txt").read_text()
    for gone in ("125%", "61.8", "positive sequence", "one second"):
        assert gone not in src
