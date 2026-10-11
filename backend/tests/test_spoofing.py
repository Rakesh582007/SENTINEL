from app.config import DetectionConfig
from app.detect.spoofing import flag_aircraft, spoofed_cells
from conftest import make

CFG = DetectionConfig()


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


def test_colocation_cluster():
    stack = [make(f"c{i:05d}", 31.0 + i * 0.001, 75.0, alt_baro=20000 + i * 4000, ts=1000 + i) for i in range(3)]
    flags = flag_aircraft(stack, CFG)
    assert all("colocation_cluster" in flags[r.hex] for r in stack)
    assert sum(spoofed_cells(flags, stack, CFG).values()) == 3


def test_simulated_spoof_is_caught():
    from app.ingest.injector import Injector
    inj = Injector()
    inj.add_spoof("aaaaaa", 25.0, 90.0, 0.0, None, now=1025)
    real = track("aaaaaa")
    seen = [inj.apply([r], now=r.ts)[0] for r in real]
    assert "impossible_jump" in flag_aircraft(seen, CFG)["aaaaaa"]
