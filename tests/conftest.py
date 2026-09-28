"""Shared test helpers. Tests use the real config/settings.yaml so the config is tested too."""
import copy
from datetime import datetime, timedelta

import pytest

from atmos.config import load_settings
from atmos.schema import Reading

T0 = datetime(2026, 1, 1, 0, 0)


@pytest.fixture
def settings():
    return copy.deepcopy(load_settings())


def make_reading(minute=0, t=20.0, p=1000.0, rh=50.0, station="S1"):
    return Reading(station_id=station, timestamp=T0 + timedelta(minutes=minute),
                   temperature_c=t, pressure_hpa=p, humidity_pct=rh)


def make_history(n, cadence=1, t=lambda i: 20.0 + 0.01 * i, p=lambda i: 1000.0 + 0.01 * i,
                 rh=lambda i: 50.0 + 0.01 * i):
    """n readings, `cadence` minutes apart. Values are small gentle ramps unless overridden."""
    return [make_reading(i * cadence, t(i), p(i), rh(i)) for i in range(n)]


def by_name(results, name):
    return next(r for r in results if r.check == name)
