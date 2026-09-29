"""evaluate_sensitivity.py: scaling the injected fault sizes and pooling the stations."""
import evaluate_sensitivity as es
from atmos.config import load_settings


def test_scaled_multiplies_only_the_swept_magnitudes_and_leaves_the_original_alone():
    s = load_settings()
    before = s["injector"]["magnitude"]["step"]["temperature_c"]
    out = es.scaled(s, 2.0)
    assert out["injector"]["magnitude"]["step"]["temperature_c"] == 2 * before
    assert out["injector"]["magnitude"]["spike"]["pressure_hpa"] == 2 * s["injector"]["magnitude"]["spike"]["pressure_hpa"]
    assert out["injector"]["magnitude"]["noise"]["humidity_pct"] == 2 * s["injector"]["magnitude"]["noise"]["humidity_pct"]
    assert s["injector"]["magnitude"]["step"]["temperature_c"] == before                 # the caller's settings are untouched
    assert out["injector"]["magnitude"]["drift"] == s["injector"]["magnitude"]["drift"]   # not swept


def test_pooled_adds_the_stations_up():
    def station(k):
        return {"station": f"S{k}", "systems": {name: {"1.0": {ty: [k, 10] for ty in es.SWEPT}} for name in es.SYSTEMS}}
    tot = es.pooled([station(3), station(5)], (1.0,))
    assert tot["full"]["1.0"]["spike"] == [8, 20]
    assert "AtmosGuard" in es.fmt(tot, (1.0,)) and "40%" in es.fmt(tot, (1.0,))
