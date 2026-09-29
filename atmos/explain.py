"""On-demand explanation of the ML layers for one reading: which features pushed it toward "unusual".

The verdict's plain-English reason comes first and exists before any model runs (rules, then the checks behind them).
This is the supporting view for the two statistical layers:

  * Mahalanobis: the squared distance splits EXACTLY into per-feature contributions (they add up to the distance).
  * Isolation Forest: SHAP TreeExplainer values. SHAP is an OPTIONAL dependency (`pip install shap`); without it that
    part says so instead of failing. The Isolation Forest is also the layer that earns least in the ablation, which is
    why the exact Mahalanobis attribution is the primary one.

Sign convention for SHAP here: negative = pushes the reading toward "unusual" (shorter isolation path).
"""
from __future__ import annotations

import importlib
from typing import Optional, Sequence

import numpy as np

from .mlmodel import FEATURE_NAMES, MAHAL_FEATURES, IsolationModel, MahalanobisModel, build_features, mahalanobis_features
from .normality import NormalityTable
from .schema import Reading

_EXPLAINERS: dict[int, object] = {}


def _tree_explainer(model: IsolationModel):
    key = id(model.forest)
    if key not in _EXPLAINERS:
        shap = importlib.import_module("shap")            # optional dependency: imported by name on purpose
        _EXPLAINERS[key] = shap.TreeExplainer(model.forest)
    return _EXPLAINERS[key]


def _ranked(names: Sequence[str], values: Sequence[float]) -> list[dict]:
    return sorted(({"feature": n, "value": round(float(v), 4)} for n, v in zip(names, values)),
                  key=lambda x: -abs(x["value"]))


def explain_isolation_forest(history: Sequence[Reading], model: IsolationModel) -> dict:
    X, ok = build_features(history[-2:])
    if len(history) < 2 or not ok[-1]:
        return {"available": False, "note": "Needs two consecutive readings with all three values."}
    score = float(model.forest.decision_function(X[-1:])[0])
    out = {"available": True, "score": round(score, 4), "threshold": round(float(model.threshold), 4),
           "flagged": score < model.threshold}
    try:
        sv = np.asarray(_tree_explainer(model).shap_values(X[-1:]))[0]
    except ImportError:
        return {**out, "shap": None, "note": "SHAP is not installed (optional): pip install shap."}
    return {**out, "shap": _ranked(FEATURE_NAMES, sv), "note": "SHAP values: negative pushes toward unusual."}


def explain_mahalanobis(history: Sequence[Reading], model: MahalanobisModel, table: Optional[NormalityTable]) -> dict:
    if model.uses_table and table is None:
        return {"available": False, "note": "This model needs the station's normality table."}
    X, ok = mahalanobis_features(history[-2:], table)
    if len(history) < 2 or not ok[-1]:
        return {"available": False, "note": "Needs two consecutive readings with all three values and a normal value for this hour."}
    D = X[-1] - model.mean
    contrib = D * (model.inv_cov @ D)
    d2 = float(contrib.sum())
    return {"available": True, "distance2": round(d2, 3), "threshold": round(float(model.threshold), 3), "flagged": d2 > model.threshold,
            "contributions": _ranked(MAHAL_FEATURES, contrib), "exact": True,
            "note": "The contributions add up to the squared distance."}


def explain_reading(history: Sequence[Reading], table: Optional[NormalityTable], iforest: Optional[IsolationModel],
                    mahal: Optional[MahalanobisModel]) -> dict:
    """`history` is oldest first and ends with the reading to explain."""
    return {"isolation_forest": explain_isolation_forest(history, iforest) if iforest else {"available": False, "note": "No Isolation Forest for this station."},
            "mahalanobis": explain_mahalanobis(history, mahal, table) if mahal else {"available": False, "note": "No Mahalanobis model for this station."}}
