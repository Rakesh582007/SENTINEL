import h3

from app.config import DetectionConfig
from app.detect.jamming import bad_reason, classify_cells, to_geojson
from app.ingest.injector import Injector
from conftest import make

CFG = DetectionConfig()
LAT, LON = 31.6, 74.9  # all test aircraft sit in this one res-3 cell
CELL = h3.latlng_to_cell(LAT, LON, CFG.h3_res)


def fleet(n_total, n_bad, **bad_fields):
    bad_fields = bad_fields or {"nac_p": 3}
    return [make(f"{i:06x}", LAT + i * 1e-4, LON, **(bad_fields if i < n_bad else {})) for i in range(n_total)]


def state_of(records):
    return classify_cells(records, CFG)[CELL]


def test_states_follow_handover_rules():
    assert state_of(fleet(2, 2)).state == "insufficient"
    assert state_of(fleet(3, 0)).state == "clear"
    assert state_of(fleet(10, 1)).state == "degraded"
    assert state_of(fleet(10, 3)).state == "degraded"  # Wilson lower bound 0.108 < 0.15
    assert state_of(fleet(10, 4)).state == "jammed"  # 0.168
    assert state_of(fleet(3, 2)).state == "jammed"  # 0.208


def test_counts_unique_aircraft_not_records():
    recs = [make("aaaaaa", LAT, LON, ts=t, nac_p=2) for t in range(10)] + fleet(3, 0)
    c = state_of(recs)
    assert c.n_aircraft == 4 and c.n_bad == 1


def test_ground_and_mlat_are_ignored():
    recs = fleet(3, 0) + [make("gggggg", LAT, LON, on_ground=True, nac_p=0), make("mmmmmm", LAT, LON, src_type="mlat", nac_p=0)]
    assert state_of(recs).n_aircraft == 3


def test_position_loss_counts_in_last_known_cell():
    lost = make("lost01", None, None, last_lat=LAT, last_lon=LON, seen=1.0, seen_pos=75.0, nac_p=None, nic=None)
    assert bad_reason(lost, CFG) == "position_lost"
    assert state_of(fleet(3, 0) + [lost]).n_bad == 1


def test_geojson_is_closed_hexagon():
    fc = to_geojson(classify_cells(fleet(3, 0), CFG))
    ring = fc["features"][0]["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 7
    assert fc["features"][0]["properties"]["state"] == "clear"


def test_simulated_jammer_turns_a_busy_cell_red_and_strength_zero_does_not():
    real = fleet(20, 0)
    inj = Injector()
    inj.add_jamming((LAT, LON), 60, 0.7, 0.0, None, now=0)
    hot = state_of(inj.apply(real, now=1))
    assert hot.state == "jammed" and hot.n_injected == hot.n_bad > 0

    inj2 = Injector()
    inj2.add_jamming((LAT, LON), 60, 0.0, 0.0, None, now=0)
    assert state_of(inj2.apply(real, now=1)).state == "clear"


def test_every_detection_threshold_has_bounds():
    from annotated_types import Ge, Le

    for name, f in DetectionConfig.model_fields.items():
        if f.annotation in (int, float):
            kinds = {type(m) for m in f.metadata}
            assert Ge in kinds and Le in kinds, f"{name} needs ge= and le="


def test_injected_and_mixed_labels():
    inj = Injector()
    inj.add_jamming((LAT, LON), 60, 1.0, 0.0, None, now=0)
    only_sim = state_of(inj.apply(fleet(10, 0), now=1))
    assert only_sim.injected and not only_sim.mixed
    both = state_of(inj.apply(fleet(10, 0), now=1) + [make("realbd", LAT, LON + 1e-4, nac_p=4)])  # not injected
    assert both.injected and both.mixed
    assert not state_of(fleet(10, 4)).injected  # real-only jamming is never labelled as a test
