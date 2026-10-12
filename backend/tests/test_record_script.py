"""scripts/record.py: the overnight recorder must survive a write error (audit S11)."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record.py"


@pytest.fixture
def record(monkeypatch):
    spec = importlib.util.spec_from_file_location("record_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # never touch this machine's power state or console mode from a test
    monkeypatch.setattr(mod, "keep_awake", lambda: "test")
    monkeypatch.setattr(mod, "disable_quickedit", lambda: "")
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def locked(*args, **kwargs):
    raise PermissionError(13, "The process cannot access the file because it is being used by another process")


def test_write_error_is_reported_and_skipped(record, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(record, "append_line", locked)
    assert record.write_line(tmp_path, {"poll_ts": 1.0}, "r000001") is None
    assert "line skipped, recording continues" in capsys.readouterr().err


def test_recorder_keeps_running_when_every_write_fails(record, tmp_path, monkeypatch):
    answer = {"ac": [{"hex": "abc123", "alt_baro": 35000, "lat": 31.6, "lon": 74.9, "nac_p": 9}], "now": 1791701082000}
    monkeypatch.setattr(record, "fetch_json", lambda url, user_agent=None: (200, answer, None, 12.0))
    monkeypatch.setattr(record, "append_line", locked)
    monkeypatch.setattr(sys, "argv", ["record.py", "--once", "--out", str(tmp_path), "--points", "31.6,74.9,100", "--sources", "adsb.fi"])
    assert record.main() == 0  # used to die with PermissionError on the first write


def test_summarize_skips_answers_that_are_not_objects(record):
    good = {"ac": [{"hex": "ABC123", "alt_baro": 30000, "nac_p": 3, "lat": 31.0}, "junk", {"hex": "def456", "alt_baro": "ground"}]}
    s = record.summarize([None, [1, 2], {"ac": "x"}, {"ac": 5}, good])
    assert s == {"union": 2, "airborne": 1, "low_nacp": 1, "no_pos": 0}
