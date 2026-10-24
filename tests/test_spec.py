"""Tests for describing your own facility in JSON."""

import json

import pytest

from ridethrough.cli import main
from ridethrough.facility import rectangular_sag, simulate
from ridethrough.grade import RIDES_THROUGH, TRIPS, grade
from ridethrough.spec import facility_from_dict, facility_from_file

MINIMAL = {
    "name": "Minimal site",
    "rated_power_mw": 80,
    "psu": {"hold_up_ms": 10, "current_limit_pu": 1.5},
}

FULL = {
    "name": "Full site",
    "rated_power_mw": 120,
    "cooling_fraction": 0.25,
    "psu": {"hold_up_ms": 10, "current_limit_pu": 1.5, "restart_s": 120},
    "ups": {"hold_up_ms": 50, "current_limit_pu": 1.2},
    "battery": {"minutes": 5},
    "protection": {"undervoltage_pickup_pu": 0.85, "delay_s": 0.1},
}


def graded(facility, depth=0.50, duration=0.5):
    traces = simulate(facility, rectangular_sag(depth, duration), duration_s=5.0)
    return grade(
        traces.voltage,
        traces.connected,
        traces.active_power,
        traces.current,
        traces.pre_disturbance_power,
        traces.max_normal_current,
    )


def test_minimal_description_builds():
    facility = facility_from_dict(MINIMAL)
    assert facility.rated_power_w == 80e6
    assert facility.ups is None
    assert facility.battery is None


def test_hold_up_is_read_in_milliseconds():
    assert facility_from_dict(MINIMAL).psu.hold_up_seconds == pytest.approx(0.010)


def test_battery_minutes_become_seconds():
    assert facility_from_dict(FULL).battery.energy_seconds == pytest.approx(300.0)


def test_battery_seconds_also_accepted():
    raw = json.loads(json.dumps(FULL))
    raw["battery"] = {"seconds": 90}
    assert facility_from_dict(raw).battery.energy_seconds == pytest.approx(90.0)


@pytest.mark.parametrize("missing", ["name", "rated_power_mw", "psu"])
def test_required_fields_are_required(missing):
    raw = json.loads(json.dumps(FULL))
    del raw[missing]
    with pytest.raises(ValueError, match=missing):
        facility_from_dict(raw)


def test_hold_up_is_required_on_a_stage():
    raw = json.loads(json.dumps(MINIMAL))
    raw["psu"] = {"current_limit_pu": 1.5}
    with pytest.raises(ValueError, match="hold_up_ms"):
        facility_from_dict(raw)


def test_a_battery_without_a_ups_is_rejected():
    raw = json.loads(json.dumps(MINIMAL))
    raw["battery"] = {"minutes": 5}
    with pytest.raises(ValueError, match="ups"):
        facility_from_dict(raw)


def test_a_battery_without_an_energy_figure_is_rejected():
    raw = json.loads(json.dumps(FULL))
    raw["battery"] = {}
    facility = facility_from_dict(raw)
    assert facility.battery is None


def test_the_shipped_example_grades():
    facility = facility_from_file("examples/facility-example.json")
    assert graded(facility).verdict == RIDES_THROUGH


def test_a_site_with_no_ups_trips_where_the_example_passes():
    assert graded(facility_from_dict(MINIMAL)).verdict == TRIPS
    assert graded(facility_from_file("examples/facility-example.json")).verdict == (
        RIDES_THROUGH
    )


# --- the check and run subcommands -------------------------------------

def write(tmp_path, raw, name="facility.json"):
    path = tmp_path / name
    path.write_text(json.dumps(raw))
    return str(path)


def test_check_passes_a_good_site(capsys):
    assert main(["check", "examples/facility-example.json"]) == 0
    assert "rides through" in capsys.readouterr().out


def test_check_fails_a_weak_site(tmp_path, capsys):
    assert main(["check", write(tmp_path, MINIMAL)]) == 1
    out = capsys.readouterr().out
    assert "trips" in out
    assert "server PSU undervoltage lockout" in out


def test_check_runs_against_every_code(tmp_path):
    for code in ("ercot", "ercot-2028", "energinet"):
        assert main(["check", write(tmp_path, FULL), "--code", code]) in (0, 1)


def test_check_writes_a_report(tmp_path):
    out = tmp_path / "report.json"
    main(["check", "examples/facility-example.json", "--out", str(out)])
    report = json.loads(out.read_text())
    assert report["verdict"] in ("rides through", "trips")
    assert "NOGRR 282" in report["source"]
    assert report["cells"]


def test_check_rejects_a_bad_file(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert main(["check", str(bad)]) == 3
    assert "error" in capsys.readouterr().err


def test_run_writes_a_scorecard_for_every_code(tmp_path):
    from ridethrough.codes import CODES

    assert main(["run", "--out", str(tmp_path / "r")]) == 0
    index = json.loads((tmp_path / "r" / "index.json").read_text())
    assert set(index["scorecards"]) == set(CODES)
    for path in index["scorecards"].values():
        assert json.loads(open(path).read())["rows"]
