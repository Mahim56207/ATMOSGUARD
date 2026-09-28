"""Loads config/settings.yaml and config/stations.yaml. Code reads thresholds from here only."""
from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load(name: str, config_dir: Path | None = None) -> dict:
    with open((config_dir or CONFIG_DIR) / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(config_dir: Path | None = None) -> dict:
    return _load("settings.yaml", config_dir)


def load_stations(config_dir: Path | None = None) -> dict[str, dict]:
    """Return {station_id: station dict}."""
    data = _load("stations.yaml", config_dir)
    return {s["id"]: s for s in data.get("stations") or []}


def layer_enabled(settings: dict, layer: str) -> bool:
    """Every layer is toggleable by a config flag."""
    return bool(settings.get("layers", {}).get(layer, False))
