"""The single-row Isolation Forest scorer must give exactly sklearn's numbers, or the speed-up would change verdicts."""
import numpy as np
import pytest

import evaluate_real as er
from atmos.config import load_settings, model_path
from atmos.mlmodel import IsolationModel, _FastForest, build_features
from tests.conftest import synthetic_readings


def _model(seed=0, **kw):
    s = load_settings()
    rd = synthetic_readings(days=15, cadence=15, seed=seed)
    m = IsolationModel.fit(rd, s)
    return m, rd


def test_fast_scores_are_bit_identical_to_sklearn_on_synthetic_data():
    m, rd = _model()
    X, usable = build_features(rd)
    want = m.forest.decision_function(X[usable])
    ff = _FastForest.build(m.forest)
    assert ff is not None
    got = np.array([ff.decision(x) for x in X[usable]])
    assert np.array_equal(got, want)


def test_fast_scores_are_bit_identical_on_real_data_for_every_committed_model():
    s = er.real_settings(load_settings())
    for sid in ("BBI", "MAA", "CCU", "DEL", "JAI", "TRV"):
        m = IsolationModel.load(model_path(s, sid, "iforest", ".joblib"))
        rd = er.to_readings(er.read_frame(er.REAL_DEV_DIR / f"{sid}.csv", s, False).iloc[3000:4500])
        X, usable = build_features(rd)
        want = m.forest.decision_function(X[usable])
        ff = _FastForest.build(m.forest)
        assert ff is not None and np.array_equal(np.array([ff.decision(x) for x in X[usable]]), want), sid


def test_model_score_uses_the_fast_path_for_a_live_pair_and_sklearn_for_a_series():
    m, rd = _model(seed=2)
    pair = rd[10:12]
    live = m.score(pair)
    assert m._fast_forest() is not None
    X, usable = build_features(pair)
    assert live[1] == m.forest.decision_function(X[usable])[0]
    series = m.score(rd[:200])                                   # batch: sklearn, one call
    assert np.isnan(series[0]) and not np.isnan(series[1:]).any()
    assert m.score(rd[10:12])[1] == m.score(rd[:200])[11]


def test_a_forest_the_fast_path_does_not_understand_falls_back_to_sklearn():
    m, rd = _model(seed=3)
    m.forest.max_features = 0.5                                   # feature sub-sampling: not handled, must not be used
    assert _FastForest.build(m.forest) is None
    m.__dict__.pop("_fast", None)
    out = m.score(rd[10:12])
    assert not np.isnan(out[1])


def test_the_saved_model_does_not_carry_the_fast_scorer(tmp_path):
    m, rd = _model(seed=4)
    m.score(rd[10:12])
    p = tmp_path / "m.joblib"
    m.save(p)
    import joblib
    assert set(joblib.load(p)) == {"station_id", "forest", "threshold"}
