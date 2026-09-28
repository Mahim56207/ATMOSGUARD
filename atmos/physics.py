"""L0 physics checks: ranges, dew point <= T, wet-bulb (soft SUSPECT flag only, never a hard rule).

Every check returns a CheckResult with a reason string. All limits come from
config/settings.yaml (section `physics`). Toggle with `layers.physics`.
"""
from __future__ import annotations

import math
from typing import Optional

from .config import layer_enabled
from .schema import CHANNELS, CheckResult, Reading

# Magnus formula constants (physical constants, not thresholds)
_MAGNUS_A = 17.62
_MAGNUS_B = 243.12


def dew_point_c(temperature_c: float, humidity_pct: float) -> float:
    """Dew point from T and RH (Magnus). Needs humidity_pct > 0."""
    g = math.log(humidity_pct / 100.0) + _MAGNUS_A * temperature_c / (_MAGNUS_B + temperature_c)
    return _MAGNUS_B * g / (_MAGNUS_A - g)


def wet_bulb_c(temperature_c: float, humidity_pct: float) -> float:
    """Wet-bulb temperature, Stull (2011) approximation. Approximate, so used as a soft flag only."""
    t, rh = temperature_c, humidity_pct
    return (
        t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )


def check_ranges(reading: Reading, settings: dict) -> list[CheckResult]:
    results = []
    for ch in CHANNELS:
        lo, hi = settings["physics"]["ranges"][ch]
        value: Optional[float] = getattr(reading, ch)
        if value is None:
            results.append(CheckResult(check=f"range:{ch}", flagged=False,
                                       reason=f"{ch} is missing, so not range-checked (dropout is handled in health)."))
        elif not (lo <= value <= hi):
            results.append(CheckResult(check=f"range:{ch}", flagged=True,
                                       reason=f"{ch} = {value} is outside the physical range [{lo}, {hi}]."))
        else:
            results.append(CheckResult(check=f"range:{ch}", flagged=False,
                                       reason=f"{ch} = {value} is inside the physical range [{lo}, {hi}]."))
    return results


def check_dew_point(reading: Reading, settings: dict) -> CheckResult:
    t, rh = reading.temperature_c, reading.humidity_pct
    if t is None or rh is None or rh <= 0:
        return CheckResult(check="dew_point", flagged=False,
                           reason="Dew point not checked: temperature or humidity is missing or not above 0.")
    tol = settings["physics"]["dew_point_tolerance_c"]
    td = dew_point_c(t, rh)
    if td > t + tol:
        return CheckResult(check="dew_point", flagged=True,
                           reason=f"Dew point {td:.1f} C is above air temperature {t} C (tolerance {tol} C). "
                                  "This is physically impossible.")
    return CheckResult(check="dew_point", flagged=False,
                       reason=f"Dew point {td:.1f} C is not above air temperature {t} C.")


def check_wet_bulb(reading: Reading, settings: dict) -> CheckResult:
    t, rh = reading.temperature_c, reading.humidity_pct
    if t is None or rh is None or rh <= 0:
        return CheckResult(check="wet_bulb", flagged=False, severity="soft",
                           reason="Wet-bulb not checked: temperature or humidity is missing or not above 0.")
    limit = settings["physics"]["wet_bulb"]["soft_flag_c"]
    tw = wet_bulb_c(t, rh)
    if tw >= limit:
        return CheckResult(check="wet_bulb", flagged=True, severity="soft",
                           reason=f"Wet-bulb {tw:.1f} C is at or above {limit} C. Very rare, so treat as "
                                  "suspicious. This is a soft flag, not proof of a fault.")
    return CheckResult(check="wet_bulb", flagged=False, severity="soft",
                       reason=f"Wet-bulb {tw:.1f} C is below the soft-flag level of {limit} C.")


def check_physics(reading: Reading, settings: dict) -> list[CheckResult]:
    """Run all L0 checks. Returns [] when the physics layer is switched off."""
    if not layer_enabled(settings, "physics"):
        return []
    return [*check_ranges(reading, settings), check_dew_point(reading, settings),
            check_wet_bulb(reading, settings)]
