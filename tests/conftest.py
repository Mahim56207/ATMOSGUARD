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


def synthetic_readings(days=20, cadence=15, seed=0, station="S1"):
    """Seeded fake weather with a daily cycle. Used ONLY for tests: nothing here is real data."""
    import math
    import numpy as np
    rng = np.random.default_rng(seed)
    n = days * 24 * 60 // cadence
    out, p = [], 1010.0
    for i in range(n):
        ts = T0 + timedelta(minutes=i * cadence)
        h = ts.hour + ts.minute / 60.0
        cycle = math.sin(2 * math.pi * (h - 9) / 24)
        p += float(rng.normal(0, 0.02))
        out.append(Reading(
            station_id=station, timestamp=ts,
            temperature_c=15 + 6 * cycle + float(rng.normal(0, 0.3)),
            pressure_hpa=p + float(rng.normal(0, 0.05)),
            humidity_pct=min(95.0, max(5.0, 60 - 15 * cycle + float(rng.normal(0, 1.0)))),
        ))
    return out
