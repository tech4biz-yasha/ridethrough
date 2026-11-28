"""The COMTRADE reader against an independent one.

This runs only where the `comtrade` package is installed. That package is
not a dependency of this one, and it needs Python 3.11 or later.
"""

import math
import warnings
from dataclasses import replace
from datetime import datetime

import pytest

comtrade = pytest.importorskip("comtrade")

from ridethrough import recording as rec  # noqa: E402


def event():
    record = rec.synthetic_recording(
        sample_rate=1920.0, duration=0.25, nominal_frequency=60.0,
        nominal_kv=230.0, voltage_pu=[(0.0, 1.0), (0.1, 0.4), (0.18, 1.0)],
        megawatts=[(0.0, 80.0)], start=datetime(2026, 3, 9, 14, 5, 6, 123456),
        name="PLANT")
    flags = tuple(1 if 0.1 <= t < 0.18 else 0 for t in record.times)
    return replace(record, device="DFR7",
                   trigger=datetime(2026, 3, 9, 14, 5, 6, 223456),
                   status=(rec.Status("TRIP", flags),
                           rec.Status("READY", tuple(1 - f for f in flags))))


def theirs(path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return comtrade.load(str(path), use_double_precision=True)


def agree(path):
    ours, other = rec.read_comtrade(path), theirs(path)
    assert ours.times == pytest.approx(list(other.time), abs=1e-12)
    assert list(ours.names) == list(other.analog_channel_ids)
    for k, channel in enumerate(ours.channels):
        assert channel.values == pytest.approx(
            [float(v) for v in other.analog_primary[k]], rel=1e-9)
    for k, status in enumerate(ours.status):
        assert list(status.values) == [int(v) for v in other.status[k]]
    assert ours.start == other.start_timestamp
    assert ours.trigger == other.trigger_timestamp
    assert ours.nominal_frequency == other.frequency
    return ours


@pytest.mark.parametrize("revision", [1991, 1999, 2013])
@pytest.mark.parametrize("binary", [False, True])
def test_both_readers_agree_on_files_written_here(tmp_path, revision, binary):
    path = tmp_path / "ours.cfg"
    rec.write_comtrade(event(), path, revision=revision, binary=binary)
    assert len(agree(path).times) == 481


@pytest.mark.parametrize("revision, kind", [
    ("1999", "ASCII"), ("1999", "BINARY"), ("2013", "ASCII"),
    ("2013", "BINARY"), ("2013", "BINARY32"), ("2013", "FLOAT32")])
def test_both_readers_agree_on_files_written_by_the_other(tmp_path, revision,
                                                          kind):
    record = event()
    rec.write_comtrade(record, tmp_path / "ours.cfg")
    path = tmp_path / "theirs.cfg"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        theirs(tmp_path / "ours.cfg").save(str(path), ft=kind, rev_year=revision)
    back = agree(path)
    for wrote, read in zip(record.channels, back.channels, strict=True):
        step = max(abs(v) for v in wrote.values) / 32767.0
        worst = max(abs(a - b) for a, b in zip(wrote.values, read.values,
                                               strict=True))
        assert not math.isnan(worst)
        assert worst <= step / 2.0 + 1e-9 * step
