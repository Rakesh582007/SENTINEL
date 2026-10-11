from app.sentinel import BASELINE_S, SentinelStore

BOX = {"id": "sentinel-1", "lat": 13.0, "lon": 80.2, "alt": 20.0, "fix": True, "avg_snr": 40.0}


def calibrated():
    s = SentinelStore(offline_s=10, max_len=500)
    t = 0.0
    while t <= BASELINE_S + 2:
        s.add(BOX, t)
        t += 2
    return s, t


def test_no_fix_is_searching_not_jamming():
    s = SentinelStore(10, 100)
    assert s.add({**BOX, "fix": False}, 0)["server_status"] == "SEARCHING"


def test_baseline_then_foil_test_then_recovery():
    s, t = calibrated()
    assert s.add(BOX, t)["server_status"] == "OK"
    assert s.add({**BOX, "avg_snr": 25.0}, t + 2)["server_status"] == "JAMMING"
    assert s.alerts(t + 2)[0]["label"].startswith("SIGNAL TEST")
    assert s.add(BOX, t + 4)["server_status"] == "OK"


def test_fix_loss_after_baseline_is_jamming():
    s, t = calibrated()
    assert s.add({**BOX, "fix": False}, t + 6)["server_status"] == "JAMMING"


def test_moving_fixed_box_is_spoof_and_offline_after_silence():
    s, t = calibrated()
    assert s.add({**BOX, "lat": 13.001}, t)["server_status"] == "SPOOF"  # ~110 m
    assert s.latest(t + 60)[0]["status"] == "OFFLINE"
