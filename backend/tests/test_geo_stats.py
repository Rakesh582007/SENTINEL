import math

from app.detect.geo import angle_diff_deg, destination_point, haversine_km, implied_speed_kt, initial_bearing_deg
from app.detect.stats import median_mad, percentile, wilson_lower_bound


def test_haversine_delhi_amritsar():
    assert abs(haversine_km(28.556, 77.100, 31.710, 74.797) - 414.8) < 1.0


def test_destination_round_trip():
    lat, lon = destination_point(31.6, 74.9, 45.0, 25.0)
    assert abs(haversine_km(31.6, 74.9, lat, lon) - 25.0) < 0.01
    assert abs(initial_bearing_deg(31.6, 74.9, lat, lon) - 45.0) < 0.1


def test_bearing_and_angle_diff():
    assert abs(initial_bearing_deg(0, 0, 0, 1) - 90.0) < 1e-6
    assert angle_diff_deg(350, 10) == 20 and angle_diff_deg(10, 350) == 20 and angle_diff_deg(0, 180) == 180


def test_implied_speed():
    assert abs(implied_speed_kt(25.0, 10.0) - 4859.6) < 1.0  # a 25 km "jump" in one poll
    assert implied_speed_kt(1.0, 0) == math.inf


def test_wilson_lower_bound():
    assert abs(wilson_lower_bound(2, 3) - 0.2077) < 1e-3  # jammed (>= 0.15)
    assert abs(wilson_lower_bound(4, 10) - 0.1682) < 1e-3  # jammed
    assert abs(wilson_lower_bound(3, 10) - 0.1078) < 1e-3  # not jammed, only degraded
    assert wilson_lower_bound(0, 5) == 0.0 and wilson_lower_bound(0, 0) == 0.0


def test_median_mad_and_percentile():
    assert median_mad([1, 2, 3, 4, 100]) == (3, 1)
    assert percentile([1, 2, 3, 4], 80) == 3.4
    assert math.isnan(percentile([], 50))
