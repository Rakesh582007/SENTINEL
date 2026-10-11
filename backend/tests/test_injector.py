from app.detect.geo import haversine_km
from app.ingest.injector import Injector, selected
from conftest import make

CENTER = (31.6, 74.9)


def hexes(n):
    return [f"{i:06x}" for i in range(n)]


def test_selection_is_deterministic_monotonic_and_proportional():
    hs = hexes(2000)
    low = {h for h in hs if selected("jam-1", h, 0.3)}
    high = {h for h in hs if selected("jam-1", h, 0.7)}
    assert low <= high  # raising Strength only adds aircraft
    assert abs(len(high) / len(hs) - 0.7) < 0.04
    assert all(selected("jam-1", h, 0.7) == (h in high) for h in hs[:100])  # same answer every poll
    assert not any(selected("jam-1", h, 0.0) for h in hs) and all(selected("jam-1", h, 1.0) for h in hs)


def test_jamming_only_inside_circle_and_only_airborne():
    inj = Injector()
    inj.add_jamming(CENTER, 60, 1.0, 0.0, None, now=0)
    inside = make("in0001", 31.7, 74.95)
    outside = make("out001", 33.5, 77.0)
    ground = make("gnd001", 31.6, 74.9, on_ground=True)
    a, b, c = inj.apply([inside, outside, ground], now=10)
    assert a.nac_p == 0 and a.nic == 0 and a.injected == "jam-1" and a.original is inside
    assert b is outside and c is ground


def test_position_loss_freezes_last_known_position():
    inj = Injector()
    inj.add_jamming(CENTER, 100, 1.0, 1.0, None, now=0)
    first = inj.apply([make("p00001", 31.60, 74.90, ts=10)], now=10)[0]
    later = inj.apply([make("p00001", 31.65, 74.98, ts=20)], now=20)[0]
    assert first.lat is None and later.lat is None
    assert (later.last_lat, later.last_lon) == (31.60, 74.90)  # frozen where GPS was "lost"
    assert later.original.lat == 31.65


def test_spoof_moves_position_and_altitude():
    inj = Injector()
    inj.add_spoof("abc123", 25.0, 90.0, -2500, None, now=0)
    real = make("abc123", 31.0, 75.0, alt_geom=36500)
    fake = inj.apply([real, make("other1", 31.0, 75.0)], now=5)
    assert abs(haversine_km(31.0, 75.0, fake[0].lat, fake[0].lon) - 25.0) < 0.01
    assert fake[0].alt_geom == 34000 and fake[0].injected.startswith("spoof-")
    assert fake[1].injected is None


def test_duration_expiry_and_ground_truth():
    inj = Injector()
    a = inj.add_jamming(CENTER, 60, 1.0, 0.0, 300, now=1000)
    assert inj.apply([make("in0001", 31.6, 74.9)], now=1100)[0].injected
    assert inj.apply([make("in0001", 31.6, 74.9)], now=1301)[0].injected is None
    assert inj.ground_truth[0]["end_ts"] == 1301 and not a.live(1301)


def test_moving_the_jammer_starts_a_new_ground_truth_event():
    inj = Injector()
    a = inj.add_jamming(CENTER, 60, 0.7, 0.3, None, now=0)
    inj.update(a.id, {"strength": 0.9}, now=10)  # slider move: same event
    assert len(inj.ground_truth) == 1 and inj.ground_truth[0]["strength"] == 0.9
    inj.update(a.id, {"center": (32.0, 75.0)}, now=20)  # new place: new event
    assert len(inj.ground_truth) == 2 and inj.ground_truth[0]["end_ts"] == 20
    inj.update(a.id, {"active": False}, now=30)
    assert inj.ground_truth[1]["end_ts"] == 30
    inj.remove(a.id, now=40)
    assert inj.attacks == {}


def test_rebase_keeps_attack_alive_across_a_replay_jump():
    inj = Injector()
    a = inj.add_jamming(CENTER, 60, 1.0, 0.0, 600, now=5000)
    inj.rebase(old_now=5100, new_now=1000)  # scrubbed back in time
    assert a.live(1000) and a.remaining_s(1000) == 500
    assert inj.ground_truth[0]["end_ts"] == 5100 and inj.ground_truth[1]["start_ts"] == 1000
    assert inj.apply([make("in0001", 31.6, 74.9)], now=1001)[0].injected == a.id
