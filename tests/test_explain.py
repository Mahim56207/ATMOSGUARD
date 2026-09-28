"""Tests for atmos/explain.py and the /explain route."""
import importlib.util

import numpy as np
import pytest
from fastapi.testclient import TestClient

import api
from atmos.explain import explain_isolation_forest, explain_mahalanobis, explain_reading
from atmos.mlmodel import IsolationModel, MahalanobisModel
from atmos.normality import NormalityTable
from atmos.store import SQLiteStore
from tests.conftest import synthetic_readings

HAS_SHAP = importlib.util.find_spec("shap") is not None


@pytest.fixture(scope="module")
def fitted():
    from atmos.config import load_settings
    s = load_settings()
    train = synthetic_readings(days=30, cadence=15, seed=1, noise_t=0.3)
    table = NormalityTable.fit(train, s)
    return s, train, table, IsolationModel.fit(train, s), MahalanobisModel.fit(train, s, table)


def test_mahalanobis_contributions_add_up_to_the_distance_and_name_the_driver(fitted):
    s, _train, table, _iso, mahal = fitted
    fresh = synthetic_readings(days=2, cadence=15, seed=9, noise_t=0.3)
    bad = fresh[:-1] + [fresh[-1].model_copy(update={"temperature_c": fresh[-1].temperature_c + 12.0})]
    ex = explain_mahalanobis(bad, mahal, table)
    assert ex["available"] and ex["exact"] and ex["flagged"]
    assert sum(c["value"] for c in ex["contributions"]) == pytest.approx(ex["distance2"], abs=0.01)
    assert ex["contributions"][0]["feature"] == "temperature_c departure"           # ranked, largest first
    # the same number the pipeline's check reports
    dist = mahal.distance2(bad[-2:], table)[-1]
    assert ex["distance2"] == pytest.approx(dist, abs=0.01)


def test_missing_pieces_are_reported_not_raised(fitted):
    s, train, table, iso, mahal = fitted
    assert not explain_mahalanobis(train[:1], mahal, table)["available"]
    assert not explain_mahalanobis(train[:5], mahal, None)["available"]
    assert not explain_isolation_forest(train[:1], iso)["available"]
    both = explain_reading(train[:5], table, None, None)
    assert not both["isolation_forest"]["available"] and not both["mahalanobis"]["available"]


@pytest.mark.skipif(not HAS_SHAP, reason="shap is an optional dependency")
def test_shap_values_cover_every_feature(fitted):
    from atmos.mlmodel import FEATURE_NAMES
    _s, train, _table, iso, _m = fitted
    ex = explain_isolation_forest(train[100:102], iso)
    assert ex["available"] and {r["feature"] for r in ex["shap"]} == set(FEATURE_NAMES)
    assert abs(ex["shap"][0]["value"]) >= abs(ex["shap"][-1]["value"])


def test_the_api_explains_the_latest_reading_of_a_trained_station():
    c = TestClient(api.create_app(store=SQLiteStore()))
    import pandas as pd
    rows = pd.read_csv("data/demo/fani_BBI_2019-05.csv").head(30)
    for _, r in rows.iterrows():
        c.post("/ingest", json={"station_id": "BBI", "timestamp": r["timestamp"], "temperature_c": r["temperature_c"],
                                "pressure_hpa": r["pressure_hpa"], "humidity_pct": r["humidity_pct"]})
    ex = c.get("/explain", params={"station_id": "BBI"}).json()
    assert ex["mahalanobis"]["available"] and len(ex["mahalanobis"]["contributions"]) == 6
    older = c.get("/explain", params={"station_id": "BBI", "record_id": ex["record_id"] - 3}).json()
    assert older["record_id"] == ex["record_id"] - 3
    assert c.get("/explain", params={"station_id": "NOPE"}).status_code == 404
    assert c.get("/explain", params={"station_id": "BBI", "record_id": 999999}).status_code == 404
