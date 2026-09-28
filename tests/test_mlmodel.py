"""Tests for atmos/mlmodel.py (L3). Uses seeded synthetic data only: the model is NOT trained on real data."""
import numpy as np
import pytest

from atmos.mlmodel import FEATURE_NAMES, IsolationModel, build_features, check_lstm_ae, check_ml
from tests.conftest import make_reading, synthetic_readings


@pytest.fixture(scope="module")
def train():
    return synthetic_readings(days=20, cadence=15, seed=0)


@pytest.fixture(scope="module")
def model(train):
    from atmos.config import load_settings
    return IsolationModel.fit(train, load_settings())


def test_features_shape_and_unusable_rows():
    rows = [make_reading(0), make_reading(15, p=None), make_reading(30)]
    X, usable = build_features(rows)
    assert X.shape == (3, len(FEATURE_NAMES)) and usable.tolist() == [False, False, False]
    X2, usable2 = build_features([make_reading(0), make_reading(15)])
    assert usable2.tolist() == [False, True]


def test_rate_feature_is_per_minute():
    X, _ = build_features([make_reading(0, t=20.0), make_reading(15, t=21.5)])
    assert X[1, FEATURE_NAMES.index("d_temperature_c_per_min")] == pytest.approx(0.1)


def _next_reading(train, **changes):
    last = train[-1]
    return last.model_copy(update={"timestamp": last.timestamp + (last.timestamp - train[-2].timestamp), **changes})


def test_unusual_mix_of_values_is_flagged_with_reason(train, model, settings):
    last = train[-1]
    odd = _next_reading(train, temperature_c=last.temperature_c + 25.0, pressure_hpa=last.pressure_hpa + 30.0,
                        humidity_pct=last.humidity_pct + 40.0)
    res = check_ml(train[-5:] + [odd], model, settings)[0]
    assert res.flagged and res.severity == "soft" and "unusual" in res.reason


def test_normal_next_reading_is_not_flagged(train, model, settings):
    res = check_ml(train[-5:] + [_next_reading(train)], model, settings)[0]
    assert not res.flagged and "inside" in res.reason


def test_false_alarm_rate_on_fresh_clean_data_is_low(model):
    fresh = synthetic_readings(days=10, cadence=15, seed=99)
    scores = model.score(fresh)
    scores = scores[~np.isnan(scores)]
    assert (scores < model.threshold).mean() < 0.03


def test_same_seed_gives_identical_model(train, settings):
    a, b = IsolationModel.fit(train, settings), IsolationModel.fit(train, settings)
    test = synthetic_readings(days=2, cadence=15, seed=5)
    assert a.threshold == b.threshold
    np.testing.assert_array_equal(a.score(test), b.score(test))


def test_save_and_load_roundtrip(model, tmp_path):
    model.save(tmp_path / "S1_iforest.joblib")
    loaded = IsolationModel.load(tmp_path / "S1_iforest.joblib")
    test = synthetic_readings(days=1, cadence=15, seed=5)
    np.testing.assert_array_equal(model.score(test), loaded.score(test))
    assert loaded.threshold == model.threshold and loaded.station_id == "S1"


def test_not_run_without_two_complete_readings(model, settings):
    res = check_ml([make_reading(0)], model, settings)[0]
    assert not res.flagged and "not run" in res.reason


def test_single_station_only(train, settings):
    with pytest.raises(ValueError):
        IsolationModel.fit(train[:50] + [make_reading(5000, station="OTHER")], settings)


def test_ml_layer_can_be_switched_off(train, model, settings):
    settings["layers"]["mlmodel"] = False
    assert check_ml(train[-3:], model, settings) == []


def test_lstm_ae_is_behind_a_flag_and_not_built(train, model, settings):
    assert len(check_ml(train[-3:], model, settings)) == 1               # flag is off by default
    settings["layers"]["lstm_ae"] = True
    with pytest.raises(NotImplementedError):
        check_ml(train[-3:], model, settings)
    with pytest.raises(NotImplementedError):
        check_lstm_ae(train[-3:], settings)


def test_absurd_values_are_skipped_instead_of_crashing_the_float32_forest(train, model, settings):
    """Found by fuzzing: 1e308 (and 3.5e38) made scikit-learn raise ValueError."""
    for huge in (1e308, -1e308, 3.5e38, 1e39):
        odd = _next_reading(train, temperature_c=huge)
        res = check_ml(train[-5:] + [odd], model, settings)[0]
        assert not res.flagged and "not run" in res.reason
    X, usable = build_features([train[-2], _next_reading(train, pressure_hpa=1e300)])
    assert usable.tolist() == [False, False]
