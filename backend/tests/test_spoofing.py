from app.config import DetectionConfig
from app.detect.spoofing import flag_aircraft, spoofed_cells
from conftest import make

CFG = DetectionConfig()
ONE_POLL = CFG.model_copy(update={"spoof_cluster_min_polls": 1})


def track(hex_id, start_lat=31.0, lon=75.0, n=6, step_deg=0.017, dt=10.0, **kw):
    """Northbound at ~450 kt: 0.017 deg latitude (~1.9 km) per 10 s."""
    return [make(hex_id, start_lat + i * step_deg, lon, ts=1000 + i * dt, track=0.0, **kw) for i in range(n)]


def test_normal_flight_is_clean():
    assert flag_aircraft(track("aaaaaa"), CFG) == {}


def test_jump_with_good_gps_is_spoofing():
    rs = track("aaaaaa")
    rs[3].lat += 0.25  # ~28 km jump inside one poll
    assert "impossible_jump" in flag_aircraft(rs, CFG)["aaaaaa"]


def test_jump_while_gps_weak_is_only_recovery():
    rs = track("aaaaaa")
    rs[3].lat += 0.25
    rs[3].nic = 0
    flags = flag_aircraft(rs, CFG)
    assert flags["aaaaaa"] == ["recovery_jump"]
    assert spoofed_cells(flags, rs, CFG) == {}


def test_pairs_closer_than_min_dt_are_ignored():
    a = make("bbbbbb", 31.0, 75.0, ts=1000)
    b = make("bbbbbb", 31.02, 75.0, ts=1001, source="adsb.lol")  # other source, 1 s later, 2 km off
    assert flag_aircraft([a, b], CFG) == {}


def peers(n=6, offset_frac=0.043):
    return [make(f"p{i:05d}", 31.0 + i * 0.3, 75.0, alt_baro=35000, alt_geom=int(35000 * (1 + offset_frac))) for i in range(n)]


def test_normal_altitude_offset_is_clean_but_minus_2500_ft_is_flagged():
    ok = make("target", 31.5, 75.2, alt_baro=35000, alt_geom=36550)  # +1,550 ft like the real data
    bad = make("target", 31.5, 75.2, alt_baro=35000, alt_geom=34000 - 1000)
    assert "target" not in flag_aircraft(peers() + [ok], CFG)
    assert "alt_offset_outlier" in flag_aircraft(peers() + [bad], CFG)["target"]


def test_lower_aircraft_scaled_offset_is_not_flagged():
    low = make("lowone", 31.5, 75.2, alt_baro=12000, alt_geom=int(12000 * 1.043))
    assert "lowone" not in flag_aircraft(peers() + [low], CFG)


def pinned_stack(polls=2):
    """Three aircraft a spoofer pins to one spot, FL200/240/280, seen on `polls` polls (like 11 Oct 23:34 IST)."""
    return [make(f"c{i:05d}", 31.0 + i * 0.001 + p * 0.0002, 75.0, alt_baro=20000 + i * 4000, ts=1000 + 10 * p + i, gs=19.0)
            for p in range(polls) for i in range(3)]


def test_colocation_cluster():
    # Since D20 a co-location must persist (pinned) for 2 polls; this was a single snapshot before.
    stack = pinned_stack(polls=2)
    flags = flag_aircraft(stack, CFG)
    assert all("colocation_cluster" in flags[r.hex] for r in stack)
    assert sum(spoofed_cells(flags, stack, CFG).values()) == 3


def test_colocation_seen_on_one_poll_only_is_not_flagged():
    assert flag_aircraft(pinned_stack(polls=1), CFG) == {}
    assert flag_aircraft(pinned_stack(polls=1), ONE_POLL)  # the old single-snapshot rule did flag it



def in_trail(polls):
    """Airway traffic in trail (12 Oct 00:40 IST): same track 127 deg, FL330/350/390, ~1 km apart
    (one just ahead, one just behind), ~530 kt = 2.7 km per 10 s poll."""
    step_lat, step_lon = -0.0146, 0.0219  # ~2.7 km along 127 deg
    out = []
    for p in range(polls):
        for i, (fl, offset) in enumerate(((330, 0.0), (350, 0.33), (390, -0.33))):
            s = p + offset
            out.append(make(f"t{fl:05d}", 29.136 + s * step_lat, 75.694 + s * step_lon,
                            ts=1000 + 10 * p + i, alt_baro=fl * 100, alt_geom=fl * 104, track=127.0, gs=530.0))
    return out


def test_stacked_airway_traffic_is_not_a_cluster():
    one = in_trail(polls=1)  # 3 aircraft, same track, FL330/350/390, < 1 km apart, one poll
    assert {tuple(v) for v in flag_aircraft(one, ONE_POLL).values()} == {("colocation_cluster",)}  # old rule: false alarm
    assert flag_aircraft(one, CFG) == {}
    assert flag_aircraft(in_trail(polls=4), CFG) == {}  # still stacked over 4 polls, but moving with the airway: not pinned


def test_jump_after_a_frozen_feed_is_a_feed_glitch_not_spoofing():
    rs = track("eeeeee", n=4)  # northbound, ~1.9 km per 10 s, reporting gs 450 kt
    frozen = make("eeeeee", rs[-1].lat + 0.0003, rs[-1].lon, ts=rs[-1].ts + 30)  # 30 s later it has barely moved
    caught_up = make("eeeeee", frozen.lat + 0.10, frozen.lon, ts=frozen.ts + 12)  # ~11 km in 12 s: the feed catching up
    recs = rs + [frozen, caught_up]
    no_guard = CFG.model_copy(update={"spoof_frozen_min_gs_kt": 600.0})
    assert flag_aircraft(recs, no_guard)["eeeeee"] == ["impossible_jump"]  # what it used to say
    flags = flag_aircraft(recs, CFG)
    assert flags["eeeeee"] == ["feed_glitch"]
    assert spoofed_cells(flags, recs, CFG) == {}


def test_three_aircraft_jumping_in_the_same_poll_is_a_feed_glitch():
    recs = []
    for k in range(3):
        rs = track(f"mass0{k}", start_lat=29.0 + k, n=4)
        rs[-1].lat += 0.25  # all three "jump" ~28 km in the same poll
        recs += rs
    flags = flag_aircraft(recs, CFG)
    assert all(flags[f"mass0{k}"] == ["feed_glitch"] for k in range(3))
    assert spoofed_cells(flags, recs, CFG) == {}
    assert flag_aircraft([r for r in recs if r.hex != "mass02"], CFG)["mass00"] == ["impossible_jump"]  # 2 is not a glitch


def test_jump_away_from_a_spoofed_fixed_point_is_still_flagged():
    # Pinned to one point while reporting ~19 kt (consistent, so not a frozen feed), then a 55 km leap.
    pinned = [make("ffffff", 31.9537 + i * 0.00005, 74.8144, ts=1000 + 10 * i, gs=19.0) for i in range(4)]
    leap = make("ffffff", 32.2047, 75.3249, ts=1050, gs=520.0)
    assert "impossible_jump" in flag_aircraft(pinned + [leap], CFG)["ffffff"]


def test_simulated_spoof_is_caught():
    from app.ingest.injector import Injector
    inj = Injector()
    inj.add_spoof("aaaaaa", 25.0, 90.0, 0.0, None, now=1025)
    real = track("aaaaaa")
    seen = [inj.apply([r], now=r.ts)[0] for r in real]
    assert "impossible_jump" in flag_aircraft(seen, CFG)["aaaaaa"]


def test_one_aircraft_with_weak_evidence_does_not_turn_a_cell_purple():
    bad = make("target", 31.5, 75.2, alt_baro=35000, alt_geom=33000)
    recs = peers() + [bad]
    flags = flag_aircraft(recs, CFG)
    assert "alt_offset_outlier" in flags["target"]
    assert spoofed_cells(flags, recs, CFG) == {}  # shown on the aircraft, not a purple cell
    bad2 = make("target2", 31.5, 75.21, alt_baro=35000, alt_geom=33000)
    assert sum(spoofed_cells(flag_aircraft(recs + [bad2], CFG), recs + [bad2], CFG).values()) == 2


def test_single_track_glitch_is_ignored_but_repeated_mismatch_is_flagged():
    rs = track("dddddd", n=8)
    rs[3].track = 120.0  # one odd reading
    assert "dddddd" not in flag_aircraft(rs, CFG)
    for r in rs[3:]:
        r.track = 120.0  # keeps claiming east while flying north
    assert "track_mismatch" in flag_aircraft(rs, CFG)["dddddd"]


def test_strong_evidence_alone_still_turns_the_cell_purple():
    rs = track("aaaaaa")
    rs[3].lat += 0.25
    assert sum(spoofed_cells(flag_aircraft(rs, CFG), rs, CFG).values()) == 1
