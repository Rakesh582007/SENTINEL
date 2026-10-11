from app.ingest.recording import append_line, iter_recording, list_recordings, make_line, new_run_id
from conftest import POLL_TS


def test_round_trip_and_truncated_tail(tmp_path, gotchas):
    run = new_run_id(POLL_TS)
    for i in range(3):
        append_line(tmp_path, make_line(POLL_TS + i, "adsb.fi", {"name": "amritsar"}, 200, 300, None, gotchas), run)
    files = list_recordings(tmp_path)
    assert len(files) == 1
    rows = list(iter_recording(files[0]))
    assert [r["poll_ts"] for r in rows] == [POLL_TS, POLL_TS + 1, POLL_TS + 2]

    damaged = tmp_path / "rec_20261011_06_rdamaged.jsonl.gz"
    damaged.write_bytes(files[0].read_bytes()[:-40])  # simulate a crash mid-write
    assert len(list(iter_recording(damaged))) == 2  # earlier lines survive


def test_each_run_writes_its_own_file(tmp_path):
    append_line(tmp_path, make_line(POLL_TS, "adsb.fi", {}, 200, 1, None, {}), "r000001")
    append_line(tmp_path, make_line(POLL_TS, "adsb.fi", {}, 200, 1, None, {}), "r000002")
    assert len(list_recordings(tmp_path)) == 2
