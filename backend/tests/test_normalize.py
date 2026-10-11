from app.ingest.normalize import epoch_seconds, merge_freshest, normalize_line, normalize_response, num
from conftest import POLL_TS, make


def by_hex(records):
    return {r.hex: r for r in records}


def test_drops_aircraft_without_hex(gotchas):
    recs = normalize_response(gotchas, "adsb.fi", POLL_TS)
    assert len(recs) == 7


def test_hex_lowercase_flight_stripped_ts_from_seen_pos(gotchas):
    r = by_hex(normalize_response(gotchas, "adsb.fi", POLL_TS))["800c6d"]
    assert r.flight == "IGO7275"
    assert abs(r.ts - (POLL_TS - 0.905)) < 1e-6
    assert r.source == "adsb.fi" and r.gps_sourced


def test_missing_fields_are_none(gotchas):
    r = by_hex(normalize_response(gotchas, "x", POLL_TS))["801527"]
    assert r.alt_baro is None and r.nac_p is None and r.flight is None
    assert r.alt_geom == 38400 and not r.on_ground


def test_ground_string(gotchas):
    r = by_hex(normalize_response(gotchas, "x", POLL_TS))["abc123"]
    assert r.on_ground and r.alt_baro is None


def test_calc_track_fallback_and_blank_flight(gotchas):
    r = by_hex(normalize_response(gotchas, "x", POLL_TS))["def456"]
    assert r.track == 88.0 and r.flight is None


def test_last_position_when_current_is_stale(gotchas):
    r = by_hex(normalize_response(gotchas, "x", POLL_TS))["aa0001"]
    assert r.lat is None and r.lon is None
    assert (r.last_lat, r.last_lon) == (31.9, 74.6)
    assert r.seen_pos == 75.0 and r.best_position() == (31.9, 74.6)
    assert abs(r.ts - (POLL_TS - 1.1)) < 1e-6  # no position: time of last message


def test_mlat_is_not_gps_sourced(gotchas):
    assert not by_hex(normalize_response(gotchas, "x", POLL_TS))["aa0002"].gps_sourced


def test_booleans_never_count_as_numbers(gotchas):
    r = by_hex(normalize_response(gotchas, "x", POLL_TS))["aa0003"]
    assert r.alt_baro is None and r.gs is None and r.nic is None
    assert r.nac_p == 7
    assert r.gps_ok_before == 1791700900.5  # milliseconds converted


def test_now_ms_or_s():
    assert epoch_seconds(1791701082000, 0) == 1791701082.0
    assert epoch_seconds(1791701082, 0) == 1791701082.0
    assert epoch_seconds(None, 5.0) == 5.0
    assert num(float("nan")) is None and num("12") is None and num(True) is None


def test_real_snapshot_normalizes(real_amritsar):
    recs = normalize_response(real_amritsar, "adsb.fi", POLL_TS)
    assert len(recs) == len(real_amritsar["ac"]) == 42
    assert all(r.hex and r.best_position() for r in recs)
    assert sum(1 for r in recs if r.nac_p is not None) > 30


def test_normalize_line_requires_http_200(gotchas):
    line = {"poll_ts": POLL_TS, "source": "adsb.lol", "http": 200, "response": gotchas}
    assert len(normalize_line(line)) == 7
    assert normalize_line({**line, "http": 429}) == []
    assert normalize_line({**line, "response": None}) == []


def test_merge_freshest_prefers_newest_position():
    old = make("a1", 30.0, 76.0, ts=100.0, source="adsb.lol")
    new = make("a1", 30.1, 76.1, ts=110.0, source="adsb.fi")
    nopos = make("a1", None, None, ts=120.0, source="adsb.fi")
    best = merge_freshest([old, nopos, new])
    assert best["a1"] is new
