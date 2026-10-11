from dataclasses import replace

from app.state import Window
from conftest import make


def test_skips_repeated_stale_positions_per_source():
    w = Window(keep_s=1800)
    a = make("a1", 30.0, 76.0, ts=100, source="adsb.fi")
    assert w.add([a, replace(a, ts=110)]) == 1  # same position polled twice
    assert w.add([make("a1", 30.0, 76.0, ts=100, source="adsb.lol")]) == 1  # other source kept
    assert w.add([make("a1", 30.1, 76.1, ts=120, source="adsb.fi")]) == 1


def test_prune_and_latest():
    w = Window(keep_s=600)
    w.add([make("a1", 30.0, 76.0, ts=0), make("a1", 30.1, 76.0, ts=500), make("b2", 31.0, 75.0, ts=700)])
    w.prune(now=800)
    assert len(w) == 2
    latest = w.latest_by_hex(now=800, max_age_s=400)
    assert latest["a1"].lat == 30.1 and set(latest) == {"a1", "b2"}


def test_restore_injected():
    w = Window(keep_s=600)
    clean = make("a1", 30.0, 76.0, ts=10)
    hit = replace(clean, nac_p=0, injected="jam-1", original=clean)
    w.add([hit])
    assert w.restore_injected("jam-1") == 1
    assert w.all()[0] is clean
