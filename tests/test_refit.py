"""refit.py: the one-command fix the `limits` notice points to."""
import pandas as pd
import pytest

import refit
from atmos.config import load_settings
from tests.test_limits import rounded_series


def write_csv(tmp_path, readings):
    p = tmp_path / "st.csv"
    pd.DataFrame([{"timestamp": r.timestamp.isoformat(), "temperature_c": r.temperature_c, "pressure_hpa": r.pressure_hpa,
                   "humidity_pct": r.humidity_pct} for r in readings]).to_csv(p, index=False)
    return p


def test_refit_writes_the_four_artifacts_and_learns_a_noise_limit(tmp_path, monkeypatch):
    s = load_settings()
    monkeypatch.setattr(refit, "load_settings", lambda: s)
    monkeypatch.setattr(refit, "model_path", lambda settings, st, kind, suffix: tmp_path / f"{st}_{kind}{suffix}")
    readings = rounded_series(seed=5)
    p = write_csv(tmp_path, readings)
    out = refit.refit(refit.read_stretch(p, "NEW1", None, None), "NEW1", s)
    assert out["warning"] is None and all(out["noise_limit_learned"].values())
    for kind, suffix in (("normality", ".json"), ("iforest", ".joblib"), ("limits", ".json"), ("mahalanobis", ".joblib")):
        assert (tmp_path / f"NEW1_{kind}{suffix}").exists()


def test_refit_refuses_a_stretch_that_is_too_short(tmp_path):
    readings = rounded_series(seed=5)[:100]
    with pytest.raises(ValueError, match="need at least"):
        refit.refit(refit.read_stretch(write_csv(tmp_path, readings), "NEW1", None, None), "NEW1", load_settings())


def test_from_and_to_cut_the_stretch(tmp_path):
    readings = rounded_series(seed=5)
    p = write_csv(tmp_path, readings)
    mid = readings[len(readings) // 2].timestamp
    a = refit.read_stretch(p, "S", str(mid), None)
    b = refit.read_stretch(p, "S", None, str(mid))
    assert len(a) + len(b) == len(readings) and min(r.timestamp for r in a) >= mid
