import pytest

from app.detect.geo import haversine_km
from app.regions import ALL_INDIA, MAX_RADIUS_NM, REGIONS, SWEEP_INTERVAL_S, QueryPoint, parse_points

AIRPORTS = {
    "SXR": (33.987, 74.774), "IXL": (34.136, 77.546), "IXJ": (32.689, 74.837), "ATQ": (31.710, 74.797),
    "IXC": (30.673, 76.788), "DEL": (28.556, 77.100), "JAI": (26.824, 75.812), "JDH": (26.251, 73.049),
    "JSA": (26.889, 70.865), "LKO": (26.761, 80.889), "VNS": (25.452, 82.859), "PAT": (25.591, 85.088),
    "CCU": (22.654, 88.447), "IXB": (26.681, 88.328), "GAU": (26.106, 91.585), "DIB": (27.483, 95.017),
    "IMF": (24.760, 93.897), "IXA": (23.887, 91.240), "BBI": (20.244, 85.818), "IXR": (23.314, 85.322),
    "RPR": (21.180, 81.739), "NAG": (21.092, 79.047), "BHO": (23.287, 77.337), "IDR": (22.722, 75.801),
    "AMD": (23.077, 72.635), "BHJ": (23.288, 69.670), "RAJ": (22.309, 70.779), "BOM": (19.089, 72.866),
    "PNQ": (18.582, 73.920), "GOI": (15.381, 73.831), "HYD": (17.240, 78.429), "VTZ": (17.721, 83.224),
    "BLR": (13.199, 77.706), "MAA": (12.994, 80.171), "IXE": (12.961, 74.890), "COK": (10.152, 76.402),
    "TRV": (8.482, 76.920), "IXM": (9.834, 78.093), "IXZ": (11.641, 92.730),
}


def test_presets_are_valid():
    for name, points in REGIONS.items():
        assert points, name
        assert name in SWEEP_INTERVAL_S
        assert all(p.radius_nm <= MAX_RADIUS_NM for p in points)


def test_all_india_reaches_every_major_airport_with_margin():
    for code, (lat, lon) in AIRPORTS.items():
        margin = max(p.radius_km - haversine_km(lat, lon, p.lat, p.lon) for p in ALL_INDIA)
        assert margin > 50, f"{code} is only {margin:.0f} km inside the nearest circle"


def test_parse_points():
    pts = parse_points("31.6,74.9,250; 28.6,77.2,150")
    assert [p.radius_nm for p in pts] == [250, 150]
    with pytest.raises(ValueError):
        parse_points("31.6,74.9")
    with pytest.raises(ValueError):
        QueryPoint("x", 31.6, 74.9, 400)
