"""Tests for the command line entry point and its exit codes."""

import json

import pytest

from ridethrough.cli import main

RUN = {
    "name": "test run",
    "pre_disturbance_power": 100.0,
    "max_normal_current": 1.0,
    "voltage": {"times": [0.0, 1.0, 1.4, 5.0], "values": [1.0, 0.65, 1.0, 1.0]},
    "connected": {"times": [0.0, 5.0], "values": [1.0, 1.0]},
    "active_power": {
        "times": [0.0, 1.0, 1.4, 1.7, 5.0],
        "values": [100.0, 60.0, 60.0, 98.0, 100.0],
    },
    "current": {"times": [0.0, 1.0, 1.4, 5.0], "values": [1.0, 1.15, 1.0, 1.0]},
}


def write(tmp_path, run, name="run.json"):
    path = tmp_path / name
    path.write_text(json.dumps(run))
    return str(path)


def test_clean_run_exits_zero(tmp_path, capsys):
    assert main([write(tmp_path, RUN)]) == 0
    assert "rides through" in capsys.readouterr().out


def test_high_current_exits_one(tmp_path, capsys):
    run = json.loads(json.dumps(RUN))
    run["current"]["values"] = [1.0, 1.6, 1.0, 1.0]
    assert main([write(tmp_path, run)]) == 1
    assert "current ceiling" in capsys.readouterr().out


def test_outside_envelope_exits_two(tmp_path):
    run = json.loads(json.dumps(RUN))
    run["voltage"]["values"] = [1.0, 0.10, 1.0, 1.0]
    assert main([write(tmp_path, run)]) == 2


def test_flat_run_exits_three(tmp_path):
    run = json.loads(json.dumps(RUN))
    run["voltage"]["values"] = [1.0, 1.0, 1.0, 1.0]
    assert main([write(tmp_path, run)]) == 3


def test_missing_field_exits_three(tmp_path, capsys):
    run = json.loads(json.dumps(RUN))
    del run["current"]
    assert main([write(tmp_path, run)]) == 3
    assert "error" in capsys.readouterr().err


def test_missing_file_exits_three(tmp_path, capsys):
    assert main([str(tmp_path / "nope.json")]) == 3


def test_json_output_is_parseable(tmp_path, capsys):
    main([write(tmp_path, RUN), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "rides through"
    assert payload["trip_driver"] is None
    # The count is not pinned: obligations appear or not depending on what
    # the run actually exercises. Pin the ones that must always be there.
    names = {c["name"] for c in payload["checks"]}
    assert {"envelope", "stays connected", "current ceiling"} <= names


@pytest.mark.parametrize("example", [
    "examples/sag_065pu_400ms.json",
    "examples/sag_065pu_400ms_high_current.json",
])
def test_shipped_examples_run(example):
    assert main([example]) in (0, 1)


# --- subcommands added in 0.2.0 ----------------------------------------

def test_bare_path_still_works_without_the_grade_word(tmp_path):
    assert main([write(tmp_path, RUN)]) == 0


def test_explicit_grade_subcommand_works(tmp_path):
    assert main(["grade", write(tmp_path, RUN)]) == 0


def test_simulate_trips_the_unprotected_site(capsys):
    code = main(["simulate", "no-ups", "--depth", "0.40", "--duration", "0.25"])
    out = capsys.readouterr().out
    assert code == 1
    assert "trips" in out
    assert "server PSU undervoltage lockout" in out


def test_simulate_passes_the_battery_site(capsys):
    code = main(["simulate", "ups-battery", "--depth", "0.65", "--duration", "0.4"])
    assert code == 0
    assert "rides through" in capsys.readouterr().out


def test_simulate_writes_a_run_file_the_grader_can_read(tmp_path):
    out = tmp_path / "runs" / "r.json"
    main(["simulate", "ups-battery", "--out", str(out)])
    assert out.exists()
    assert main(["grade", str(out)]) == 0


def test_simulate_json_is_parseable(capsys):
    main(["simulate", "no-ups", "--depth", "0.40", "--duration", "0.25", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "trips"
    assert payload["model_trip_driver"]


def test_sweep_prints_every_archetype(capsys):
    from ridethrough.archetypes import ARCHETYPES

    assert main(["sweep"]) == 0
    out = capsys.readouterr().out
    for key in ARCHETYPES:
        assert key in out
    assert "Modelled, not measured" in out


def test_sweep_writes_a_table(tmp_path):
    out = tmp_path / "scorecard.json"
    main(["sweep", "--out", str(out)])
    table = json.loads(out.read_text())
    from ridethrough.envelope import ERCOT_VOLTAGE

    assert len(table["points"]) == len(ERCOT_VOLTAGE.corner_points())
    assert "02-080126.docx" in table["source"]
    for row in table["rows"].values():
        assert len(row["cells"]) == len(table["points"])


def test_piping_into_head_does_not_raise(tmp_path):
    """A tool that prints a traceback when piped into head is a rough edge.
    The default SIGPIPE handler makes the process end quietly instead."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    piped = subprocess.run(
        f"{sys.executable} -m ridethrough.cli sweep | head -3",
        shell=True,
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert "BrokenPipeError" not in piped.stderr
    assert "Traceback" not in piped.stderr
