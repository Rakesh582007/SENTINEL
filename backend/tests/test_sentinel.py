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
    e = s.add({**BOX, "avg_snr": 18.0}, t + 2)
    assert e["server_status"] == "JAMMING" and "below 22" in e["server_reason"]
    assert s.alerts(t + 2)[0]["label"].startswith("SIGNAL TEST")
    assert s.add(BOX, t + 4)["server_status"] == "OK"


def test_jamming_only_below_22_db_hz_not_on_a_drop_from_baseline():
    """13 Oct: indoors the box sat at 28-30 dB-Hz with a 39 baseline and kept reading JAMMING."""
    s, t = calibrated()
    assert s.add({**BOX, "avg_snr": 25.0}, t)["server_status"] == "OK"  # 15 dB below baseline, still above 22
    assert s.add({**BOX, "avg_snr": 22.0}, t + 2)["server_status"] == "OK"  # exactly 22 is normal
    assert s.add({**BOX, "avg_snr": 21.9}, t + 4)["server_status"] == "JAMMING"


def test_lost_fix_with_normal_signal_is_not_jamming():
    s, t = calibrated()
    e = s.add({**BOX, "fix": False, "avg_snr": 29.0}, t + 600)
    assert e["server_status"] == "OK" and e["server_reason"] == "no fix, signal normal"
    assert s.add({**BOX, "fix": False, "avg_snr": 0.0}, t + 602)["server_status"] == "JAMMING"  # foil: signal gone


def test_moving_fixed_box_is_spoof_and_offline_after_silence():
    s, t = calibrated()
    assert s.add({**BOX, "lat": 13.001}, t)["server_status"] == "SPOOF"  # ~110 m
    assert s.latest(t + 60)[0]["status"] == "OFFLINE"
