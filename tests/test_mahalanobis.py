"""Tests for the Mahalanobis layer in atmos/mlmodel.py."""
import numpy as np
import pytest

from atmos.fusion import Pipeline
from atmos.mlmodel import MahalanobisModel, check_mahalanobis, mahalanobis_features
from atmos.normality import NormalityTable
from atmos.schema import Verdict
from tests.conftest import synthetic_readings


@pytest.fixture(scope="module")
def fitted():
    from atmos.config import load_settings
    s = load_settings()
    train = synthetic_readings(days=30, cadence=15, seed=1, noise_t=0.3)
    table = NormalityTable.fit(train, s)
    return s, train, table, MahalanobisModel.fit(train, s, table)


def test_a_clean_reading_is_inside_the_limit(fitted):
    s, _train, table, model = fitted
    fresh = synthetic_readings(days=3, cadence=15, seed=9, noise_t=0.3)
    flags = [check_mahalanobis(fresh[: i + 1], model, table, s)[0].flagged for i in range(2, len(fresh))]
    assert np.mean(flags) < 0.03                               # about the training quantile, not a flood


def test_a_departure_in_one_channel_is_flagged_and_named(fitted):
    s, _train, table, model = fitted
    fresh = synthetic_readings(days=2, cadence=15, seed=9, noise_t=0.3)
    bad = fresh[:-1] + [fresh[-1].model_copy(update={"temperature_c": fresh[-1].temperature_c + 12.0})]
    res = check_mahalanobis(bad, model, table, s)[0]
    assert res.flagged and res.severity == "soft" and "temperature_c departure" in res.reason


def test_switching_the_layer_off_gives_no_checks(fitted):
    s, _train, table, model = fitted
    s = {**s, "layers": {**s["layers"], "mahalanobis": False}}
    assert check_mahalanobis(synthetic_readings(days=1, cadence=15), model, table, s) == []


def test_the_pipeline_uses_it_and_never_makes_it_a_fault_on_its_own(fitted):
    s, _train, table, model = fitted
    pipe = Pipeline(s, {"S1": {"cadence_minutes": 15}}, {"S1": table}, None, None, {"S1": model})
    fresh = synthetic_readings(days=2, cadence=15, seed=9, noise_t=0.3)
    verdicts = [pipe.process(r) for r in fresh[:-1]]
    v = pipe.process(fresh[-1].model_copy(update={"temperature_c": fresh[-1].temperature_c + 6.0}))
    assert any(c.check == "mahalanobis" for c in v.checks)
    assert v.verdict != Verdict.FAULT or any(c.check.startswith(("step", "range", "frozen")) and c.flagged for c in v.checks)


def test_save_and_load_round_trip(fitted, tmp_path):
    s, train, table, model = fitted
    model.save(tmp_path / "m.joblib")
    back = MahalanobisModel.load(tmp_path / "m.joblib")
    a, b = model.distance2(train[:50], table), back.distance2(train[:50], table)
    assert np.allclose(a[~np.isnan(a)], b[~np.isnan(b)]) and back.threshold == model.threshold


def test_features_are_departures_and_rates(fitted):
    _s, train, table, _m = fitted
    X, ok = mahalanobis_features(train[:5], table)
    assert not ok[0] and ok[1:].all() and X.shape == (5, 6)
    assert abs(X[2, 0] - (train[2].temperature_c - table.smooth_expected(train[2].timestamp, "temperature_c"))) < 1e-9


def test_fit_refuses_two_stations_and_too_little_data(fitted):
    s, train, table, _m = fitted
    mixed = train[:100] + [r.model_copy(update={"station_id": "OTHER"}) for r in train[100:200]]
    with pytest.raises(ValueError):
        MahalanobisModel.fit(mixed, s, table)
    with pytest.raises(ValueError):
        MahalanobisModel.fit(train[:20], s, table)


def test_it_still_runs_when_the_normality_checks_are_switched_off(fitted):
    """The model is trained on departures from the table, so 'no normality layer' must not change its inputs."""
    s, _train, table, model = fitted
    off = {**s, "layers": {**s["layers"], "normality": False}}
    pipe = Pipeline(off, {"S1": {"cadence_minutes": 15}}, {"S1": table}, None, None, {"S1": model})
    fresh = synthetic_readings(days=2, cadence=15, seed=9, noise_t=0.3)
    verdicts = [pipe.process(r) for r in fresh]
    flagged = sum(any(c.check == "mahalanobis" and c.flagged for c in v.checks) for v in verdicts)
    assert flagged / len(verdicts) < 0.05


def test_a_table_model_without_a_table_says_it_did_not_run(fitted):
    s, train, _table, model = fitted
    res = check_mahalanobis(train[:5], model, None, s)[0]
    assert not res.flagged and "needs the station's normality table" in res.reason
