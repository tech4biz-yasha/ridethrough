"""Read recorder files, and turn sampled waveforms into the quantities a
ride-through rule is written in.

A rule such as NERC PRC-029-2 speaks of fundamental RMS voltage per phase,
frequency, rate of change of frequency, positive sequence phase angle and
Real Power. A fault recorder stores none of those. It stores instantaneous
samples. This module does the step in between, and nothing more. It does
not grade anything.

Files read: COMTRADE `.cfg` with `.dat` in the 1991, 1999 and 2013 layouts,
as text or binary, and CSV with a header row.

How each quantity is computed, and what that leaves uncertain, is set out
in docs/RECORDINGS.md.
"""

from __future__ import annotations

import bisect
import cmath
import csv
import math
import re
import struct
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from .grade import Trace
from .prc029 import CONTINUOUS_REGION, Table

MISSING = float("nan")
PHASE_TO_NEUTRAL = "phase-to-neutral"
PHASE_TO_PHASE = "phase-to-phase"

_ALPHA = cmath.exp(2j * math.pi / 3.0)
_VOLTS = {"V": 1.0, "v": 1.0, "kV": 1e3, "KV": 1e3, "kv": 1e3, "MV": 1e6,
          "mV": 1e-3}
_AMPS = {"A": 1.0, "a": 1.0, "kA": 1e3, "KA": 1e3, "ka": 1e3, "mA": 1e-3}
_TIME_CODE = re.compile(r"^([+-]?)(\d{1,2})(?:[hH](\d{1,2}))?$")
_END_OF_FILE = "\x1a"


@dataclass(frozen=True)
class Channel:
    """One analogue channel: instantaneous values in the unit stated."""

    name: str
    values: tuple[float, ...]
    unit: str = ""
    phase: str = ""


@dataclass(frozen=True)
class Status:
    """One status channel: 0 or 1 at each sample."""

    name: str
    values: tuple[int, ...]


@dataclass(frozen=True)
class Recording:
    """One recorder file.

    `times` are seconds from the first sample. `start` is the clock time of
    the first sample as the file writes it, and `utc_offset` is how far that
    clock is ahead of UTC where the file says so. `sample_rate` is set only
    when the whole record has one rate.
    """

    name: str
    times: tuple[float, ...]
    channels: tuple[Channel, ...]
    nominal_frequency: float
    sample_rate: float | None = None
    start: datetime | None = None
    trigger: datetime | None = None
    utc_offset: timedelta | None = None
    status: tuple[Status, ...] = ()
    device: str = ""

    def __post_init__(self) -> None:
        if len(self.times) < 2:
            raise ValueError("a record needs at least two samples")
        for ch in self.channels:
            if len(ch.values) != len(self.times):
                raise ValueError(f"channel {ch.name} does not match the time base")
        for st in self.status:
            if len(st.values) != len(self.times):
                raise ValueError(f"status {st.name} does not match the time base")

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(ch.name for ch in self.channels)

    @property
    def duration(self) -> float:
        return self.times[-1] - self.times[0]

    @property
    def trigger_time(self) -> float | None:
        """Seconds from the first sample to the trigger, where the file gives both."""
        if self.start is None or self.trigger is None:
            return None
        return (self.trigger - self.start).total_seconds()

    def channel(self, name: str) -> Channel:
        for ch in self.channels:
            if ch.name == name:
                return ch
        raise KeyError(f"no channel {name!r}; this record has {list(self.names)}")

    def shifted(self, seconds: float) -> Recording:
        """The same record with its clock moved by `seconds`."""
        if self.start is None:
            raise ValueError("this record has no start time to shift")
        moved = timedelta(seconds=seconds)
        trigger = None if self.trigger is None else self.trigger + moved
        return replace(self, start=self.start + moved, trigger=trigger)


# ---------------------------------------------------------------- COMTRADE

def _text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return text.replace(_END_OF_FILE, "")


def _stamp(text: str, revision: int) -> tuple[datetime | None, int]:
    """A COMTRADE date and time, and how many fraction digits it carried.

    The 1991 layout writes mm/dd/yy. Later layouts write dd/mm/yyyy. A year
    written with two digits is read as 1970 to 2069.
    """
    try:
        date, clock = (part.strip() for part in text.split(",", 1))
        first, second, year_text = (x.strip() for x in date.split("/"))
        year = int(year_text)
        if len(year_text) == 2:
            year += 2000 if year < 70 else 1900
        if revision < 1999:
            month, day = int(first), int(second)
        else:
            day, month = int(first), int(second)
        hours, minutes, seconds = clock.split(":")
        whole, _, fraction = seconds.strip().partition(".")
        micro = int((fraction + "000000")[:6]) if fraction else 0
        when = datetime(year, month, day, int(hours), int(minutes), int(whole), micro)
        return when, len(fraction)
    except (ValueError, IndexError):
        return None, 0


def _utc_offset(code: str) -> timedelta | None:
    """The 2013 time code, such as -5h30 or 0, as an offset from UTC."""
    found = _TIME_CODE.match(code.strip())
    if not found:
        return None
    hours, minutes = int(found.group(2)), int(found.group(3) or 0)
    if hours > 23 or minutes > 59:
        return None
    offset = timedelta(hours=hours, minutes=minutes)
    return -offset if found.group(1) == "-" else offset


def _dat_path(cfg: Path) -> Path:
    for suffix in (".dat", ".DAT", ".Dat"):
        candidate = cfg.with_suffix(suffix)
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no .dat file beside {cfg}")


def read_comtrade(cfg, dat=None, *, primary: bool = True,
                  nominal_frequency: float | None = None) -> Recording:
    """Read a COMTRADE `.cfg` and its `.dat`.

    Values come back in the unit the file states, on the primary side of the
    instrument transformer unless `primary` is False. The sample rate in the
    `.cfg` sets the time base where the file gives one. Otherwise the time
    stamps in the `.dat` do. Channel skew is not applied.
    """
    cfg = Path(cfg)
    dat = Path(dat) if dat is not None else _dat_path(cfg)
    lines = [ln.strip() for ln in _text(cfg).splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    try:
        return _read_comtrade(cfg, dat, lines, primary, nominal_frequency)
    except IndexError:
        raise ValueError(f"{cfg} ends before the COMTRADE layout does") from None


def _read_comtrade(cfg, dat, lines, primary, nominal_frequency) -> Recording:
    head = [x.strip() for x in lines[0].split(",")]
    revision = int(head[2]) if len(head) > 2 and head[2].isdigit() else 1991
    counts = [x.strip() for x in lines[1].split(",")]
    n_analog = int(counts[1].rstrip("Aa"))
    n_status = int(counts[2].rstrip("Dd"))

    analog = []
    for ln in lines[2:2 + n_analog]:
        f = [x.strip() for x in ln.split(",")]
        if len(f) < 7 or not f[5]:
            named = f[1] if len(f) > 1 else ln
            raise ValueError(f"{cfg}: channel {named} has no multiplier")
        scale = 1.0
        if len(f) >= 13 and f[10] and f[11]:
            first, second, side = float(f[10]), float(f[11]), f[12].upper()
            if primary and side == "S" and first > 0 and second > 0:
                scale = first / second
            elif not primary and side == "P" and first > 0 and second > 0:
                scale = second / first
        analog.append((f[1], f[2], f[4], float(f[5]), float(f[6] or 0.0), scale))
    at = 2 + n_analog
    status_names = [ln.split(",")[1].strip() for ln in lines[at:at + n_status]]
    at += n_status

    stated = lines[at].strip()
    frequency = nominal_frequency or (float(stated) if stated else 0.0)
    if not frequency:
        raise ValueError("the file states no line frequency; pass nominal_frequency")
    n_rates = int(lines[at + 1])
    rates = []
    for ln in lines[at + 2:at + 2 + max(n_rates, 1)]:
        samp, end = ln.split(",")
        rates.append((float(samp), int(end)))
    at += 2 + max(n_rates, 1)
    start, digits = _stamp(lines[at], revision)
    trigger, _ = _stamp(lines[at + 1], revision)
    file_type = lines[at + 2].strip().upper()
    multiplier = 1.0
    if len(lines) > at + 3 and lines[at + 3]:
        multiplier = float(lines[at + 3])
    offset = None
    if revision >= 2013 and len(lines) > at + 4 and lines[at + 4]:
        offset = _utc_offset(lines[at + 4].split(",")[0])
    declared = rates[-1][1]

    stamps, raw, bits = _read_dat(dat, file_type, revision, n_analog, n_status,
                                  declared)
    count = len(stamps)
    if count < 2:
        raise ValueError(f"{dat} holds fewer than two samples")
    if declared and count < declared:
        warnings.warn(f"{dat} holds {count} samples; the .cfg states {declared}",
                      stacklevel=3)

    one_rate = None
    if n_rates >= 1 and all(samp > 0 for samp, _ in rates):
        times, t, segment = [0.0], 0.0, 0
        for i in range(1, count):
            while segment < len(rates) - 1 and i >= rates[segment][1]:
                segment += 1
            t += 1.0 / rates[segment][0]
            times.append(t)
        if len(rates) == 1:
            one_rate = rates[0][0]
            times = [i / one_rate for i in range(count)]
    else:
        if any(s is None for s in stamps):
            raise ValueError(f"{dat} has a missing time stamp and the .cfg "
                             "states no sample rate")
        unit = 1e-9 if digits > 6 else 1e-6
        times = [(s - stamps[0]) * multiplier * unit for s in stamps]
        one_rate = _uniform_rate(times)

    channels = []
    for k, (name, phase, unit, a, b, scale) in enumerate(analog):
        values = tuple(
            MISSING if x is None else (a * x + b) * scale for x in raw[k]
        )
        channels.append(Channel(name, values, unit, phase))
    status = tuple(Status(name, tuple(bits[k]))
                   for k, name in enumerate(status_names))
    return Recording(
        name=head[0] or cfg.stem, device=head[1] if len(head) > 1 else "",
        times=tuple(times), channels=tuple(channels),
        nominal_frequency=frequency, sample_rate=one_rate,
        start=start, trigger=trigger, utc_offset=offset, status=status,
    )


def _read_dat(dat: Path, file_type: str, revision: int, n_analog: int,
              n_status: int, declared: int):
    """Time stamps, raw analogue values and status bits. None marks a missing
    value."""
    stamps = []
    raw = [[] for _ in range(n_analog)]
    bits = [[] for _ in range(n_status)]
    if file_type == "ASCII":
        width = 2 + n_analog + n_status
        gone = ("", "99999") if revision >= 1999 else ("",)
        for number, ln in enumerate(_text(dat).splitlines(), start=1):
            if not ln.strip():
                continue
            f = [x.strip() for x in ln.split(",")]
            if len(f) != width:
                raise ValueError(f"{dat} line {number} has {len(f)} fields; "
                                 f"the .cfg calls for {width}")
            stamps.append(float(f[1]) if f[1] else None)
            for k in range(n_analog):
                cell = f[2 + k]
                raw[k].append(None if cell in gone else float(cell))
            for k in range(n_status):
                bits[k].append(int(f[2 + n_analog + k]))
            if declared and len(stamps) >= declared:
                break
        return stamps, raw, bits

    code = {"BINARY": "h", "BINARY32": "i", "FLOAT32": "f"}.get(file_type)
    if code is None:
        raise ValueError(f"unsupported COMTRADE data file type {file_type!r}")
    words = (n_status + 15) // 16
    layout = struct.Struct("<II" + code * n_analog + "H" * words)
    gone = None
    if revision >= 1999:
        gone = {"h": -32768, "i": -2147483648,
                "f": struct.unpack("<f", b"\xff\xff\x7f\xff")[0]}[code]
    data = dat.read_bytes()
    usable = len(data) - len(data) % layout.size
    for row in layout.iter_unpack(data[:usable]):
        stamps.append(None if row[1] == 0xFFFFFFFF else float(row[1]))
        for k in range(n_analog):
            x = row[2 + k]
            raw[k].append(None if x == gone else float(x))
        for k in range(n_status):
            word = row[2 + n_analog + k // 16]
            bits[k].append((word >> (k % 16)) & 1)
        if declared and len(stamps) >= declared:
            break
    return stamps, raw, bits


def write_comtrade(recording: Recording, cfg, dat=None, *, revision: int = 1999,
                   binary: bool = False) -> None:
    """Write a record as COMTRADE with 16 bits per sample.

    This is here to make test events in the format recorders write. Each
    channel is scaled so its largest sample sits at full scale, so a value
    read back can differ from the one written by half a step, which is the
    channel's largest value divided by 65534.
    """
    if revision not in (1991, 1999, 2013):
        raise ValueError("revision must be 1991, 1999 or 2013")
    if recording.sample_rate is None:
        raise ValueError("writing needs a record with one sample rate")
    if recording.start is None:
        raise ValueError("writing needs a record with a start time")
    cfg = Path(cfg)
    dat = Path(dat) if dat is not None else cfg.with_suffix(".dat")
    count = len(recording.times)
    first = f"{recording.name},{recording.device}"
    out = [first if revision == 1991 else f"{first},{revision}"]
    n_a, n_d = len(recording.channels), len(recording.status)
    out.append(f"{n_a + n_d},{n_a}A,{n_d}D")
    scaled = []
    for k, ch in enumerate(recording.channels, start=1):
        if any(math.isnan(x) for x in ch.values):
            raise ValueError(f"channel {ch.name} has missing samples")
        peak = max(abs(x) for x in ch.values)
        a = peak / 32767.0 if peak else 1.0
        scaled.append([round(x / a) for x in ch.values])
        line = f"{k},{ch.name},{ch.phase},,{ch.unit},{a!r},0.0,0.0,-32767,32767"
        out.append(line if revision == 1991 else line + ",1.0,1.0,P")
    for k, st in enumerate(recording.status, start=1):
        out.append(f"{k},{st.name},0" if revision == 1991 else f"{k},{st.name},,,0")
    out.append(f"{recording.nominal_frequency:g}")
    out.append("1")
    out.append(f"{recording.sample_rate!r},{count}")

    def stamp(when: datetime) -> str:
        if revision == 1991:
            date = f"{when.month:02d}/{when.day:02d}/{when.year % 100:02d}"
        else:
            date = f"{when.day:02d}/{when.month:02d}/{when.year:04d}"
        return (f"{date},{when.hour:02d}:{when.minute:02d}:"
                f"{when.second:02d}.{when.microsecond:06d}")

    out.append(stamp(recording.start))
    out.append(stamp(recording.trigger or recording.start))
    out.append("BINARY" if binary else "ASCII")
    if revision >= 1999:
        out.append("1")
    if revision == 2013:
        out.append(f"{_time_code(recording.utc_offset)},x")
        out.append("0,0")
    cfg.write_text("\n".join(out) + "\n", encoding="utf-8")

    micro = [round(t * 1e6) for t in recording.times]
    if micro[-1] > 0xFFFFFFFE:
        raise ValueError("this record is too long for COMTRADE time stamps")
    if binary:
        words = (n_d + 15) // 16
        layout = struct.Struct("<II" + "h" * n_a + "H" * words)
        blob = bytearray()
        for i in range(count):
            packed = [0] * words
            for k, st in enumerate(recording.status):
                packed[k // 16] |= (st.values[i] & 1) << (k % 16)
            blob += layout.pack(i + 1, micro[i], *(col[i] for col in scaled), *packed)
        dat.write_bytes(bytes(blob))
    else:
        rows = []
        for i in range(count):
            cells = [str(i + 1), str(micro[i])]
            cells += [str(col[i]) for col in scaled]
            cells += [str(st.values[i]) for st in recording.status]
            rows.append(",".join(cells))
        dat.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _time_code(offset: timedelta | None) -> str:
    if offset is None:
        return "x"
    minutes = round(offset.total_seconds() / 60.0)
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    if not minutes:
        return "0"
    return f"{sign}{hours}h{rest:02d}" if rest else f"{sign}{hours}"


# --------------------------------------------------------------------- CSV

def _uniform_rate(times: Sequence[float]) -> float | None:
    steps = [b - a for a, b in zip(times, times[1:], strict=False)]
    if not steps or min(steps) <= 0:
        return None
    if max(steps) - min(steps) > 1e-9 + 1e-6 * steps[0]:
        return None
    return (len(times) - 1) / (times[-1] - times[0])


def _rows(path: Path, columns: Sequence[str]) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) < 2:
        raise ValueError(f"{path} holds fewer than two rows of data")
    for column in columns:
        if column not in rows[0]:
            raise KeyError(f"{path} has no column {column!r}")
    return rows


def read_csv(path, *, time: str, channels: Mapping[str, str] | Sequence[str],
             nominal_frequency: float, units: Mapping[str, str] | None = None,
             time_scale: float = 1.0, start: datetime | None = None) -> Recording:
    """Read sampled waveforms from a CSV file with a header row.

    `time` names the time column, and `time_scale` is what one unit of that
    column is in seconds, so 0.001 for milliseconds. `channels` maps the
    channel names you want to the column names in the file, or is a list of
    column names to use as they are. `units` gives each channel its unit.
    """
    path = Path(path)
    wanted = dict(channels) if isinstance(channels, Mapping) else {
        c: c for c in channels}
    rows = _rows(path, [time, *wanted.values()])
    stamps = [float(r[time]) * time_scale for r in rows]
    times = tuple(s - stamps[0] for s in stamps)
    units = dict(units or {})
    made = tuple(
        Channel(name, tuple(float(r[column]) for r in rows), units.get(name, ""))
        for name, column in wanted.items()
    )
    return Recording(name=path.stem, times=times, channels=made,
                     nominal_frequency=nominal_frequency,
                     sample_rate=_uniform_rate(times), start=start)


def read_trace_csv(path, *, time: str, value: str, time_scale: float = 1.0,
                   value_scale: float = 1.0) -> Trace:
    """Read one quantity that is already computed, such as RMS voltage or
    megawatts, from a CSV file with a header row."""
    path = Path(path)
    rows = _rows(path, [time, value])
    stamps = [float(r[time]) * time_scale for r in rows]
    return Trace([s - stamps[0] for s in stamps],
                 [float(r[value]) * value_scale for r in rows])


# ----------------------------------------------------------------- phasors

@dataclass(frozen=True)
class Phasors:
    """Fundamental phasors, one per sample from the end of the first cycle.

    Each value is an RMS phasor against a reference turning at `frequency`,
    so a steady signal at exactly that frequency has a constant angle. Each
    is stamped with the time of the last sample in its window.
    """

    times: tuple[float, ...]
    values: tuple[complex, ...]
    frequency: float
    samples_per_cycle: int


def _window(recording: Recording, at_frequency: float | None = None) -> int:
    if recording.sample_rate is None:
        raise ValueError("this needs a record with one sample rate")
    fitted = at_frequency or recording.nominal_frequency
    if fitted <= 0:
        raise ValueError("the frequency must be positive")
    per_cycle = round(recording.sample_rate / fitted)
    if per_cycle < 8:
        raise ValueError("this needs at least 8 samples per cycle")
    if len(recording.times) < per_cycle:
        raise ValueError("this record is shorter than one cycle")
    return per_cycle


def phasors(recording: Recording, channel: str, *,
            at_frequency: float | None = None) -> Phasors:
    """Fundamental phasors of one channel.

    At each sample, a constant plus a sine and a cosine are fitted by least
    squares to the last cycle of samples. The constant takes up any DC
    offset. The sine and cosine are at the nominal frequency unless
    `at_frequency` gives another, for a record where the system sat away
    from nominal.
    """
    m = _window(recording, at_frequency)
    fitted = at_frequency or recording.nominal_frequency
    x = recording.channel(channel).values
    if any(math.isnan(v) for v in x):
        raise ValueError(f"channel {channel} has missing samples")
    omega = 2.0 * math.pi * fitted
    sums = [[0.0] for _ in range(8)]
    for t, v in zip(recording.times, x, strict=True):
        c, s = math.cos(omega * t), math.sin(omega * t)
        for run, term in zip(sums, (v, v * c, v * s, c, s, c * c, s * s, c * s),
                             strict=True):
            run.append(run[-1] + term)
    root2 = math.sqrt(2.0)
    times, values = [], []
    for k in range(m - 1, len(x)):
        sx, sxc, sxs, sc, ss, scc, sss, scs = (
            run[k + 1] - run[k + 1 - m] for run in sums)
        # Solve [[m, sc, ss], [sc, scc, scs], [ss, scs, sss]] [c0, a, b] = rhs
        # for a and b, the cosine and sine parts, by Cramer's rule.
        det = (m * (scc * sss - scs * scs) - sc * (sc * sss - scs * ss)
               + ss * (sc * scs - scc * ss))
        a = (m * (sxc * sss - scs * sxs) - sx * (sc * sss - scs * ss)
             + ss * (sc * sxs - sxc * ss)) / det
        b = (m * (scc * sxs - sxc * scs) - sc * (sc * sxs - sxc * ss)
             + sx * (sc * scs - scc * ss)) / det
        times.append(recording.times[k])
        values.append(complex(a, -b) / root2)
    return Phasors(tuple(times), tuple(values), fitted, m)


def _trace(times: Sequence[float], values: Sequence[float], what: str) -> Trace:
    if len(times) < 2:
        raise ValueError(f"this record is too short to give {what}")
    return Trace(list(times), list(values))


def _same_base(*sets: Phasors) -> None:
    for other in sets[1:]:
        if other.times != sets[0].times:
            raise ValueError("these phasors are not on the same time base")


def phase_to_phase(first: Phasors, second: Phasors) -> Phasors:
    """The phasor of first minus second, for example A to B."""
    _same_base(first, second)
    values = tuple(p - q for p, q in zip(first.values, second.values, strict=True))
    return replace(first, values=values)


def positive_sequence(a: Phasors, b: Phasors, c: Phasors) -> Phasors:
    """Positive sequence phasor of three phase phasors in the order A, B, C."""
    _same_base(a, b, c)
    values = tuple(
        (p + _ALPHA * q + _ALPHA * _ALPHA * r) / 3.0
        for p, q, r in zip(a.values, b.values, c.values, strict=True)
    )
    return replace(a, values=values)


def rms(of: Phasors) -> Trace:
    """Fundamental RMS magnitude."""
    return _trace(of.times, [abs(v) for v in of.values], "an RMS trace")


def angle_degrees(of: Phasors) -> Trace:
    """Phase angle in degrees, unwrapped so it does not jump at 180."""
    out, last, turns = [], None, 0.0
    for v in of.values:
        now = math.degrees(cmath.phase(v))
        if last is not None:
            if now - last > 180.0:
                turns -= 360.0
            elif now - last < -180.0:
                turns += 360.0
        last = now
        out.append(now + turns)
    return _trace(of.times, out, "a phase angle trace")


def angle_jump(angle: Trace, *, period: float) -> Trace:
    """Change in angle over `period`, less the change over the period before.

    A steady frequency offset turns the angle at a constant rate, and that
    cancels. A sudden jump shows at its full size once the window has passed
    over it, and then once more with the opposite sign.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    times, values = [], []
    for k, t in enumerate(angle.times):
        if t - 2.0 * period < angle.times[0] - 1e-12:
            continue
        j = bisect.bisect_right(angle.times, t - period + 1e-12) - 1
        i = bisect.bisect_right(angle.times, t - 2.0 * period + 1e-12) - 1
        times.append(t)
        values.append(angle.values[k] - 2.0 * angle.values[j] + angle.values[i])
    return _trace(times, values, "a phase angle jump over that period")


def frequency(of: Phasors, *, cycles: int) -> Trace:
    """Frequency in hertz, measured over `cycles` cycles.

    The reference turns at the nominal frequency, so the measured frequency
    is the nominal one plus the rate at which the angle moves.
    """
    if cycles < 1:
        raise ValueError("cycles must be at least 1")
    span = cycles * of.samples_per_cycle
    angle = angle_degrees(of)
    times, values = [], []
    for k in range(span, len(angle.times)):
        turned = (angle.values[k] - angle.values[k - span]) / 360.0
        took = angle.times[k] - angle.times[k - span]
        times.append(angle.times[k])
        values.append(of.frequency + turned / took)
    return _trace(times, values, f"frequency over {cycles} cycles")


def rate_of_change(of: Trace, *, period: float) -> Trace:
    """Average rate of change of a trace over the `period` before each sample."""
    if period <= 0:
        raise ValueError("period must be positive")
    times, values = [], []
    for k, t in enumerate(of.times):
        back = t - period
        if back < of.times[0] - 1e-12:
            continue
        j = bisect.bisect_right(of.times, back + 1e-12) - 1
        times.append(t)
        values.append((of.values[k] - of.values[j]) / (t - of.times[j]))
    return _trace(times, values, "a rate of change over that period")


# ------------------------------------------------- voltage in per unit, power

def per_unit(of: Trace, base: float) -> Trace:
    if base <= 0:
        raise ValueError("the base must be positive")
    return Trace(list(of.times), [v / base for v in of.values])


def _pointwise(traces: Sequence[Trace], pick) -> Trace:
    if not traces:
        raise ValueError("at least one trace is needed")
    for other in traces[1:]:
        if list(other.times) != list(traces[0].times):
            raise ValueError("these traces are not on the same time base")
    columns = zip(*(tr.values for tr in traces), strict=True)
    return Trace(list(traces[0].times), [pick(col) for col in columns])


def lowest(traces: Sequence[Trace]) -> Trace:
    """At each sample, the lowest of several traces."""
    return _pointwise(traces, min)


def highest(traces: Sequence[Trace]) -> Trace:
    """At each sample, the highest of several traces."""
    return _pointwise(traces, max)


def _scale(recording: Recording, channel: str, units: Mapping[str, float],
           kind: str) -> float:
    unit = recording.channel(channel).unit
    if unit not in units:
        raise ValueError(f"channel {channel} has unit {unit!r}; a {kind} channel "
                         f"needs one of {sorted(set(units))}")
    return units[unit]


def voltage_per_unit(recording: Recording, *, channels: Sequence[str],
                     nominal_kv: float, basis: str,
                     at_frequency: float | None = None) -> tuple[Trace, Trace]:
    """Lowest and highest fundamental RMS voltage across the phases, per unit.

    `channels` are the three phase-to-neutral voltage channels in the order
    A, B, C. `nominal_kv` is the nominal phase-to-phase voltage. `basis` is
    PHASE_TO_NEUTRAL, which measures each channel against nominal_kv / √3,
    or PHASE_TO_PHASE, which measures A-B, B-C and C-A against nominal_kv.
    `at_frequency` is passed to `phasors`.
    """
    if len(channels) != 3:
        raise ValueError("give the three phase-to-neutral channels, A, B, C")
    if nominal_kv <= 0:
        raise ValueError("nominal_kv must be positive")
    sets = [phasors(recording, name, at_frequency=at_frequency)
            for name in channels]
    kv = [_scale(recording, name, _VOLTS, "voltage") / 1e3 for name in channels]
    sets = [replace(p, values=tuple(v * k for v in p.values))
            for p, k in zip(sets, kv, strict=True)]
    if basis == PHASE_TO_NEUTRAL:
        base = nominal_kv / math.sqrt(3.0)
    elif basis == PHASE_TO_PHASE:
        a, b, c = sets
        sets = [phase_to_phase(a, b), phase_to_phase(b, c), phase_to_phase(c, a)]
        base = nominal_kv
    else:
        raise ValueError(f"basis must be {PHASE_TO_NEUTRAL!r} or {PHASE_TO_PHASE!r}")
    traces = [per_unit(rms(p), base) for p in sets]
    return lowest(traces), highest(traces)


def real_power(recording: Recording, *, voltages: Sequence[str],
               currents: Sequence[str], sign: float = 1.0) -> Trace:
    """Real power in megawatts, averaged over each cycle.

    The instantaneous products of each phase-to-neutral voltage and its line
    current are added, and the sum is averaged over the last cycle. `sign`
    is -1 where the current transformers point the other way.
    """
    if len(voltages) != len(currents) or not voltages:
        raise ValueError("give one current channel for each voltage channel")
    m = _window(recording)
    volts, amps = [], []
    for v_name, i_name in zip(voltages, currents, strict=True):
        k = _scale(recording, v_name, _VOLTS, "voltage")
        volts.append([x * k for x in recording.channel(v_name).values])
        k = _scale(recording, i_name, _AMPS, "current")
        amps.append([x * k for x in recording.channel(i_name).values])
    run = [0.0]
    for i in range(len(recording.times)):
        total = sum(v[i] * c[i] for v, c in zip(volts, amps, strict=True))
        if math.isnan(total):
            raise ValueError("a voltage or current channel has missing samples")
        run.append(run[-1] + total)
    times, values = [], []
    for k in range(m - 1, len(recording.times)):
        times.append(recording.times[k])
        values.append(sign * (run[k + 1] - run[k + 1 - m]) / m / 1e6)
    return _trace(times, values, "a power trace")


# ------------------------------------------------------ deviations and window

def deviations(low: Trace, high: Trace, table: Table) -> list[tuple[float, float]]:
    """Each stretch where voltage is outside the continuous operation region.

    `low` and `high` are the lowest and highest per-unit phase voltages. A
    deviation starts at the first sample where either is in a row of `table`
    that is not in the continuous operation region, and ends at the first
    later sample where both are back in it. That is this package's reading
    of "deviations" in PRC-029-2 Attachment 1, item 9. A deviation still
    open at the end of the record ends at the last sample.
    """
    if list(low.times) != list(high.times):
        raise ValueError("low and high are not on the same time base")
    found, began = [], None
    for t, lo, hi in zip(low.times, low.values, high.values, strict=True):
        outside = (table.region(lo) != CONTINUOUS_REGION
                   or table.region(hi) != CONTINUOUS_REGION)
        if outside and began is None:
            began = t
        elif not outside and began is not None:
            found.append((began, t))
            began = None
    if began is not None:
        found.append((began, low.times[-1]))
    return found


def event_window(low: Trace, high: Trace, table: Table, *, before: float = 0.0,
                 after: float = 0.0) -> tuple[float, float] | None:
    """From the start of the first deviation to the end of the last one,
    widened by `before` and `after` seconds and kept inside the record.
    None when the record holds no deviation."""
    found = deviations(low, high, table)
    if not found:
        return None
    return (max(low.times[0], found[0][0] - before),
            min(low.times[-1], found[-1][1] + after))


# ------------------------------------------------------------------ alignment

def align(recordings: Sequence[Recording]) -> tuple[float, ...]:
    """Seconds from the earliest start to the start of each record.

    Where every record states its offset from UTC, the starts are compared
    in UTC. Where none does, they are compared as written. A mix of the two
    is refused, because the answer would rest on a guess.
    """
    if not recordings:
        raise ValueError("at least one record is needed")
    if any(r.start is None for r in recordings):
        raise ValueError("every record needs a start time to be aligned")
    stated = [r.utc_offset is not None for r in recordings]
    if any(stated) and not all(stated):
        raise ValueError("some of these records state their offset from UTC "
                         "and some do not; set utc_offset on each first")
    starts = [r.start - (r.utc_offset or timedelta(0)) for r in recordings]
    earliest = min(starts)
    return tuple((s - earliest).total_seconds() for s in starts)


def shift(of: Trace, seconds: float) -> Trace:
    """The same trace with every time moved by `seconds`."""
    return Trace([t + seconds for t in of.times], list(of.values))


# ------------------------------------------------------------ synthetic events

def _held(steps: Sequence[tuple[float, float]], t: float) -> float:
    value = steps[0][1]
    for when, level in steps:
        if when <= t + 1e-12:
            value = level
        else:
            break
    return value


def synthetic_recording(
    *, sample_rate: float, duration: float, nominal_frequency: float,
    nominal_kv: float,
    voltage_pu: Sequence[tuple[float, float]] | Mapping[str, Sequence],
    megawatts: Sequence[tuple[float, float]] | None = None,
    frequency_hz: Sequence[tuple[float, float]] | None = None,
    phase_jump: tuple[float, float] | None = None,
    start: datetime | None = None, name: str = "synthetic",
) -> Recording:
    """A three-phase record built from stated steps, for tests and examples.

    `voltage_pu`, `megawatts` and `frequency_hz` are lists of (time, value)
    steps, each held until the next. `voltage_pu` may instead map "A", "B"
    and "C" to their own steps. `phase_jump` is (time, degrees). Channels
    are VA, VB, VC in kV phase-to-neutral and IA, IB, IC in kA, with each
    current in phase with its voltage.
    """
    count = int(round(duration * sample_rate)) + 1
    times = tuple(i / sample_rate for i in range(count))
    per_phase = voltage_pu if isinstance(voltage_pu, Mapping) else {
        "A": voltage_pu, "B": voltage_pu, "C": voltage_pu}
    line_to_neutral = nominal_kv / math.sqrt(3.0)
    root2 = math.sqrt(2.0)
    turn = {"A": 0.0, "B": -2.0 * math.pi / 3.0, "C": 2.0 * math.pi / 3.0}
    volts = {p: [] for p in "ABC"}
    amps = {p: [] for p in "ABC"}
    theta, last = 0.0, 0.0
    for t in times:
        f = _held(frequency_hz, last) if frequency_hz else nominal_frequency
        theta += 2.0 * math.pi * f * (t - last)
        last = t
        jump = 0.0
        if phase_jump and t >= phase_jump[0] - 1e-12:
            jump = math.radians(phase_jump[1])
        power = _held(megawatts, t) if megawatts else 0.0
        for p in "ABC":
            level = _held(per_phase[p], t) * line_to_neutral
            wave = math.cos(theta + jump + turn[p])
            volts[p].append(root2 * level * wave)
            current = power / (3.0 * level) if level > 0 else 0.0
            amps[p].append(root2 * current * wave)
    channels = tuple(
        [Channel(f"V{p}", tuple(volts[p]), "kV", p) for p in "ABC"]
        + [Channel(f"I{p}", tuple(amps[p]), "kA", p) for p in "ABC"]
    )
    return Recording(name=name, times=times, channels=channels,
                     nominal_frequency=nominal_frequency, sample_rate=sample_rate,
                     start=start or datetime(2026, 1, 1))
