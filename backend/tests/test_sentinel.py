from app.sentinel import BASELINE_S, SentinelStore

BOX = {"id": "sentinel-1", "lat": 13.0, "lon": 80.2, "alt": 20.0, "fix": True, "avg_snr": 40.0}


def calibrated():
    s = SentinelStore(offline_s=10, max_len=500)
    t = 0.0
    while t <= BASELINE_S + 2:
        s.add(BOX, t)
        t += 2
    return s, t


def test_no_signal_reading_is_searching_but_a_normal_signal_is_ok_without_a_fix():
    s = SentinelStore(10, 100)
    assert s.add({"id": "sentinel-1", "fix": False}, 0)["server_status"] == "SEARCHING"
    e = s.add({**BOX, "fix": False}, 2)  # never had a fix, signal 40: normal
    assert e["server_status"] == "OK" and e["server_reason"] == "no fix, signal normal"


def test_never_had_a_fix_and_signal_below_22_is_jamming_after_the_hold():
    """13 Oct 06:16 screenshot: 0 of 9 satellites used for 3 hours, average 19 dB-Hz, status stuck on SEARCHING."""
    s = SentinelStore(10, 100)
    first = s.add({**BOX, "fix": False, "sats_used": 0, "avg_snr": 19.0}, 0)
    assert first["server_status"] == "OK" and "confirming" in first["server_reason"]
    e = None
    for k in range(1, 5):
        e = s.add({**BOX, "fix": False, "sats_used": 0, "avg_snr": 19.0}, 2 * k)
    assert e["server_status"] == "JAMMING"
    assert s.add({**BOX, "fix": False, "avg_snr": 22.0}, 10)["server_status"] == "OK"


def feed(s, t, snr, seconds, **extra):
    """Send one packet every 2 s for `seconds`; returns the last entry and the next time."""
    e = None
    for _ in range(int(seconds // 2)):
        e = s.add({**BOX, "avg_snr": snr, **extra}, t)
        t += 2
    return e, t


def test_baseline_then_foil_test_then_recovery():
    s, t = calibrated()
    assert s.add(BOX, t)["server_status"] == "OK"
    e, t = feed(s, t + 2, 18.0, 10)  # foil on the antenna for 10 s
    assert e["server_status"] == "JAMMING" and "below 22" in e["server_reason"]
    assert s.alerts(t)[0]["label"].startswith("SIGNAL TEST")
    assert s.add(BOX, t)["server_status"] == "OK"


def test_a_short_dip_below_22_does_not_flip_the_status():
    """13 Oct chart: single samples dipped under 22 indoors; they must not flash JAMMING."""
    s, t = calibrated()
    e = s.add({**BOX, "avg_snr": 12.0}, t)
    assert e["server_status"] == "OK" and "confirming" in e["server_reason"]
    assert s.add({**BOX, "avg_snr": 15.0}, t + 2)["server_status"] == "OK"
    assert s.add({**BOX, "avg_snr": 28.0}, t + 4)["server_status"] == "OK"  # back above 22: timer reset
    assert s.add({**BOX, "avg_snr": 12.0}, t + 6)["server_status"] == "OK"  # a new dip starts from zero
    assert s.add({**BOX, "avg_snr": 12.0}, t + 8)["server_status"] == "OK"
    assert s.add({**BOX, "avg_snr": 12.0}, t + 10)["server_status"] == "OK"  # 4 s < hold
    assert s.add({**BOX, "avg_snr": 12.0}, t + 12)["server_status"] == "JAMMING"  # 6 s in a row
    assert s.add({**BOX, "avg_snr": 22.0}, t + 14)["server_status"] == "OK"  # leaves at once at 22


def test_hold_zero_reacts_to_the_first_packet():
    s = SentinelStore(10, 100, jam_hold_s=0)
    s.add(BOX, 0)
    assert s.add({**BOX, "avg_snr": 15.0}, 2)["server_status"] == "JAMMING"


def test_silence_resets_the_hold_timer():
    s, t = calibrated()
    s.add({**BOX, "avg_snr": 12.0}, t)
    e = s.add({**BOX, "avg_snr": 12.0}, t + 300)  # box was offline in between: not "300 s of jamming"
    assert e["server_status"] == "OK"


def test_screenshot_case_above_22_without_a_fix_is_never_jamming():
    """13 Oct screenshot: no fix, 0/2 satellites, average 24 dB-Hz, baseline 39."""
    s, t = calibrated()
    for k in range(60):  # a long stretch without a fix
        e = s.add({**BOX, "fix": False, "sats_used": 0, "avg_snr": 24.0}, t + 2 * k)
        assert e["server_status"] == "OK", e
    assert e["server_reason"] == "no fix, signal normal"


def test_each_reading_carries_the_rule_so_a_stale_backend_is_visible():
    e = SentinelStore(10, 100).add(BOX, 0)
    assert e["rule"] == {"v": 3, "jam_snr_db": 22.0, "jam_hold_s": 6.0}


def test_jamming_only_below_22_db_hz_not_on_a_drop_from_baseline():
    """13 Oct: indoors the box sat at 28-30 dB-Hz with a 39 baseline and kept reading JAMMING."""
    s, t = calibrated()
    assert s.add({**BOX, "avg_snr": 25.0}, t)["server_status"] == "OK"  # 15 dB below baseline, still above 22
    assert s.add({**BOX, "avg_snr": 22.0}, t + 2)["server_status"] == "OK"  # exactly 22 is normal
    e, _ = feed(s, t + 4, 21.9, 8)
    assert e["server_status"] == "JAMMING"


def test_lost_fix_with_normal_signal_is_not_jamming():
    s, t = calibrated()
    e = s.add({**BOX, "fix": False, "avg_snr": 29.0}, t + 600)
    assert e["server_status"] == "OK" and e["server_reason"] == "no fix, signal normal"
    e = None
    for k in range(4):  # foil: signal gone for 6 s
        e = s.add({**BOX, "fix": False, "avg_snr": 0.0}, t + 602 + 2 * k)
    assert e["server_status"] == "JAMMING"


def test_moving_fixed_box_is_spoof_and_offline_after_silence():
    s, t = calibrated()
    assert s.add({**BOX, "lat": 13.001}, t)["server_status"] == "SPOOF"  # ~110 m
    assert s.latest(t + 60)[0]["status"] == "OFFLINE"
