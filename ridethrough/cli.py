"""Command line entry point.

    ridethrough grade run.json
    ridethrough simulate ups-battery --depth 0.65 --duration 0.4
    ridethrough sweep

`grade` is the default, so `ridethrough run.json` still works.

Exit codes, so this can sit in a pipeline:

    0  rides through
    1  trips
    2  not required (the disturbance fell outside the envelope)
    3  error (the run tested nothing, or the input is malformed)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .archetypes import ARCHETYPES
from .codes import CODES, ERCOT
from .facility import rectangular_sag, repeated_sags, simulate
from .grade import ERROR, NOT_REQUIRED, RIDES_THROUGH, TRIPS, Trace, grade
from .spec import facility_from_file

EXIT_CODES = {RIDES_THROUGH: 0, TRIPS: 1, NOT_REQUIRED: 2, ERROR: 3}
MARKS = {True: "pass", False: "FAIL", None: "n/a "}
SUBCOMMANDS = {"grade", "simulate", "sweep", "repeated", "codes", "run", "check"}

# The sweep points are derived from whichever envelope is in play, not
# chosen by hand. Each one is a flat sag held for exactly as long as that
# code allows at that depth, which is the worst case it actually requires.


def _trace(raw: dict, name: str) -> Trace:
    try:
        return Trace(times=raw[name]["times"], values=raw[name]["values"])
    except KeyError as exc:
        raise ValueError(f"run file is missing {name}: {exc}") from exc


def _grade_dict(raw: dict, code=ERCOT):
    return grade(
        code=code,
        voltage=_trace(raw, "voltage"),
        connected=_trace(raw, "connected"),
        active_power=_trace(raw, "active_power"),
        current=_trace(raw, "current"),
        pre_disturbance_power=raw["pre_disturbance_power"],
        max_normal_current=raw["max_normal_current"],
    )


def _payload(name, result, model_driver=None, model_time=None) -> dict:
    return {
        "run": name,
        "verdict": result.verdict,
        "trip_driver": result.trip_driver,
        "model_trip_driver": model_driver,
        "model_trip_time": model_time,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "detail": c.detail,
                "margin": c.margin,
            }
            for c in result.checks
        ],
    }


def _print(payload) -> None:
    print(f"run:     {payload['run']}")
    print(f"verdict: {payload['verdict']}")
    if payload.get("trip_driver"):
        print(f"driver:  {payload['trip_driver']}")
    if payload.get("model_trip_driver"):
        when = payload.get("model_trip_time")
        when_text = f" at {when * 1000:.0f} ms" if when is not None else ""
        print(f"physics: {payload['model_trip_driver']}{when_text}")
    for c in payload["checks"]:
        print(f"  [{MARKS[c['passed']]}] {c['name']}: {c['detail']}")


def cmd_grade(args) -> int:
    try:
        with args.run.open() as handle:
            raw = json.load(handle)
        result = _grade_dict(raw, CODES[args.code])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CODES[ERROR]

    payload = _payload(raw.get("name", args.run.stem), result)
    print(json.dumps(payload, indent=2)) if args.json else _print(payload)
    return EXIT_CODES[result.verdict]


def cmd_simulate(args) -> int:
    if args.archetype not in ARCHETYPES:
        print(
            f"error: unknown archetype {args.archetype!r}. "
            f"choose from {', '.join(sorted(ARCHETYPES))}",
            file=sys.stderr,
        )
        return EXIT_CODES[ERROR]

    facility = ARCHETYPES[args.archetype](args.rated_power)
    traces = simulate(
        facility,
        rectangular_sag(args.depth, args.duration, args.start),
        duration_s=args.total,
    )
    code = CODES[args.code]
    result = grade(
        traces.voltage,
        traces.connected,
        traces.active_power,
        traces.current,
        traces.pre_disturbance_power,
        traces.max_normal_current,
        code=code,
    )
    name = (
        f"{facility.name}, sag to {args.depth:.2f} pu "
        f"for {args.duration * 1000:.0f} ms, against {code.name}"
    )
    payload = _payload(name, result, traces.trip_driver, traces.trip_time)

    if args.out:
        run_dict = traces.as_run(name)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(run_dict, indent=2))

    print(json.dumps(payload, indent=2)) if args.json else _print(payload)
    return EXIT_CODES[result.verdict]


def cmd_sweep(args) -> int:
    code = CODES[args.code]
    corners = code.voltage.corner_points()
    names = sorted(ARCHETYPES)
    rows = {}
    for key in names:
        facility = ARCHETYPES[key](args.rated_power)
        cells = []
        for depth, duration in corners:
            traces = simulate(
                facility,
                rectangular_sag(depth, duration, 0.5),
                duration_s=max(5.0, duration + 3.0),
            )
            result = grade(
                traces.voltage,
                traces.connected,
                traces.active_power,
                traces.current,
                traces.pre_disturbance_power,
                traces.max_normal_current,
                code=code,
            )
            cells.append(
                {
                    "depth_pu": depth,
                    "duration_s": duration,
                    "verdict": result.verdict,
                    "trip_driver": result.trip_driver,
                    "model_trip_driver": traces.trip_driver,
                    "model_trip_time_s": traces.trip_time,
                }
            )
        rows[key] = {"facility": facility.name, "cells": cells}

    table = {
        "code": code.name,
        "envelope": code.voltage.name,
        "source": code.source,
        "points": [{"depth_pu": d, "duration_s": t} for d, t in corners],
        "rows": rows,
        "note": (
            "Modelled, not measured. Archetypes are configurations, not sites."
        ),
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(table, indent=2))

    if args.json:
        print(json.dumps(table, indent=2))
        return 0

    short = {RIDES_THROUGH: "pass", TRIPS: "TRIP", NOT_REQUIRED: "n/r", ERROR: "err"}
    labels = [f"{d:.2f}/{t:g}s" for d, t in corners]
    widths = [max(len(label), 6) for label in labels]
    header = "  ".join(
        f"{label:>{width}s}" for label, width in zip(labels, widths, strict=True)
    )
    print(f"code: {code.name}")
    print(f"{'archetype':24s}  {header}")
    print("-" * (24 + 2 + len(header)))
    for key in names:
        cells = rows[key]["cells"]
        line = "  ".join(
            f"{short[c['verdict']]:>{width}s}"
            for c, width in zip(cells, widths, strict=True)
        )
        print(f"{key:24s}  {line}")
    print()
    print(
        f"Modelled, not measured. Each point is the longest sag {code.name} "
        f"allows at that depth."
    )
    return 0


def cmd_repeated(args) -> int:
    """A train of sags, which is the northern Virginia failure mode."""
    code = CODES[args.code]
    facility = ARCHETYPES[args.archetype](args.rated_power)
    span = args.start + args.count * args.interval + 5.0
    traces = simulate(
        facility,
        repeated_sags(args.depth, args.duration, args.count, args.interval, args.start),
        duration_s=span,
    )
    result = grade(
        traces.voltage,
        traces.connected,
        traces.active_power,
        traces.current,
        traces.pre_disturbance_power,
        traces.max_normal_current,
        code=code,
    )
    name = (
        f"{facility.name}, {args.count} sags to {args.depth:.2f} pu of "
        f"{args.duration * 1000:.0f} ms every {args.interval:g} s, "
        f"against {code.name}"
    )
    payload = _payload(name, result, traces.trip_driver, traces.trip_time)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(traces.as_run(name), indent=2))
    print(json.dumps(payload, indent=2)) if args.json else _print(payload)
    return EXIT_CODES[result.verdict]


def cmd_codes(args) -> int:
    for key, code in CODES.items():
        print(f"{key}")
        print(f"  {code.name}")
        print(f"  envelope: {code.voltage.name}")
        limit = (
            f"{code.current_limit_pu:.2f} x normal"
            if code.current_limit_pu is not None
            else "none set"
            + (", blocking permitted" if code.current_blocking_allowed else "")
        )
        print(f"  current ceiling: {limit}")
        points = ", ".join(
            f"{p.fraction:.0%} in {p.seconds:g} s" for p in code.recovery
        )
        print(f"  recovery: {points}")
        print(f"  source: {code.source}")
        print()
    return 0


def cmd_check(args) -> int:
    """Grade one facility description against every corner of a code."""
    try:
        facility = facility_from_file(args.facility)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CODES[ERROR]

    code = CODES[args.code]
    corners = code.voltage.corner_points()
    cells = []
    worst = RIDES_THROUGH
    for depth, duration in corners:
        traces = simulate(
            facility,
            rectangular_sag(depth, duration, 0.5),
            duration_s=max(5.0, duration + 3.0),
        )
        result = grade(
            traces.voltage,
            traces.connected,
            traces.active_power,
            traces.current,
            traces.pre_disturbance_power,
            traces.max_normal_current,
            code=code,
        )
        cells.append(
            {
                "depth_pu": depth,
                "duration_s": duration,
                "verdict": result.verdict,
                "trip_driver": result.trip_driver,
                "model_trip_driver": traces.trip_driver,
                "model_trip_time_s": traces.trip_time,
            }
        )
        if result.verdict == TRIPS:
            worst = TRIPS

    report = {
        "facility": facility.name,
        "code": code.name,
        "source": code.source,
        "verdict": worst,
        "cells": cells,
        "note": "Modelled from the description supplied. Not a measurement.",
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2))
    if args.json:
        print(json.dumps(report, indent=2))
        return EXIT_CODES[worst]

    print(f"facility: {facility.name}")
    print(f"code:     {code.name}")
    print()
    for cell in cells:
        mark = "pass" if cell["verdict"] == RIDES_THROUGH else cell["verdict"]
        held = f"{cell['duration_s']:g} s"
        line = f"  {cell['depth_pu']:.2f} pu held {held:>7s}   {mark:<13s}"
        if cell["model_trip_driver"]:
            line += f"   {cell['model_trip_driver']}"
        print(line)
    print()
    print(f"overall: {worst}")
    return EXIT_CODES[worst]


def cmd_run(args) -> int:
    """Everything, in one command. Writes a scorecard per code."""
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for key in sorted(CODES):
        sweep_args = argparse.Namespace(
            code=key,
            rated_power=args.rated_power,
            out=out / f"scorecard-{key}.json",
            json=False,
        )
        cmd_sweep(sweep_args)
        print()
        summary[key] = str(sweep_args.out)
    (out / "index.json").write_text(
        json.dumps(
            {
                "generated_by": f"ridethrough {__version__}",
                "scorecards": summary,
                "note": (
                    "Modelled, not measured. Archetypes are configurations, "
                    "not sites."
                ),
            },
            indent=2,
        )
    )
    print(f"wrote {len(summary)} scorecards and an index to {out}/")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "grade")

    parser = argparse.ArgumentParser(
        prog="ridethrough",
        description="Grade data centre ride-through claims against a grid code.",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    p_grade = subs.add_parser("grade", help="grade a run described in JSON")
    p_grade.add_argument("run", type=Path)
    p_grade.add_argument("--json", action="store_true")
    p_grade.add_argument("--code", choices=sorted(CODES), default="ercot")
    p_grade.set_defaults(func=cmd_grade)

    p_sim = subs.add_parser("simulate", help="model a facility and grade it")
    p_sim.add_argument("archetype", choices=sorted(ARCHETYPES))
    p_sim.add_argument("--depth", type=float, default=0.65, help="sag depth in pu")
    p_sim.add_argument("--duration", type=float, default=0.4, help="seconds")
    p_sim.add_argument("--start", type=float, default=0.5)
    p_sim.add_argument("--total", type=float, default=5.0)
    p_sim.add_argument("--rated-power", type=float, default=50e6, help="watts")
    p_sim.add_argument("--out", type=Path, help="write the run file here")
    p_sim.add_argument("--json", action="store_true")
    p_sim.add_argument("--code", choices=sorted(CODES), default="ercot")
    p_sim.set_defaults(func=cmd_simulate)

    p_sweep = subs.add_parser(
        "sweep", help="every archetype against the ERCOT band corners"
    )
    p_sweep.add_argument("--rated-power", type=float, default=50e6)
    p_sweep.add_argument("--out", type=Path, help="write the table here")
    p_sweep.add_argument("--json", action="store_true")
    p_sweep.add_argument("--code", choices=sorted(CODES), default="ercot")
    p_sweep.set_defaults(func=cmd_sweep)

    p_rep = subs.add_parser(
        "repeated", help="a train of sags, the northern Virginia failure mode"
    )
    p_rep.add_argument("archetype", choices=sorted(ARCHETYPES))
    p_rep.add_argument("--depth", type=float, default=0.30)
    p_rep.add_argument("--duration", type=float, default=0.06)
    p_rep.add_argument("--count", type=int, default=6)
    p_rep.add_argument("--interval", type=float, default=13.0)
    p_rep.add_argument("--start", type=float, default=0.5)
    p_rep.add_argument("--rated-power", type=float, default=50e6)
    p_rep.add_argument("--out", type=Path)
    p_rep.add_argument("--json", action="store_true")
    p_rep.add_argument("--code", choices=sorted(CODES), default="ercot")
    p_rep.set_defaults(func=cmd_repeated)

    p_codes = subs.add_parser("codes", help="show the codes and their values")
    p_codes.set_defaults(func=cmd_codes)

    p_check = subs.add_parser(
        "check", help="grade your own facility, described in JSON"
    )
    p_check.add_argument("facility", type=Path)
    p_check.add_argument("--code", choices=sorted(CODES), default="ercot")
    p_check.add_argument("--out", type=Path)
    p_check.add_argument("--json", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_run = subs.add_parser(
        "run", help="every archetype against every code, in one command"
    )
    p_run.add_argument("--rated-power", type=float, default=50e6)
    p_run.add_argument("--out", type=Path, default=Path("results"))
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
