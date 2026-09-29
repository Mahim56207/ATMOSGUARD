"""The two remedies proposed in docs/HOLDOUT_POSTMORTEM.md, behind flags that are OFF by default (so nothing that was
reported changes): a ceiling-aware frozen rule and a station-learned step cap."""
import numpy as np
import pytest

from atmos.config import load_settings
from atmos.health import check_frozen, check_step
from atmos.limits import ChannelLimits, StationLimits, fit_limits, learned_step_cap
from tests.conftest import make_history, make_reading
from tests.test_limits import rounded_series

CAD = 60


def limits_with(frozen_min=600.0, step_cap=None):
    ch = {c: ChannelLimits(frozen_minutes=frozen_min, step_cap=step_cap) for c in ("temperature_c", "pressure_hpa", "humidity_pct")}
    return StationLimits("S1", float(CAD), ch)


def frozen_history(hours, t=26.0, p=1000.0, rh=100.0):
    return make_history(hours + 1, cadence=CAD, t=lambda i: t, p=lambda i: p, rh=lambda i: rh)


# ---- remedy 1 --------------------------------------------------------------------------------------------------
def test_flags_are_off_by_default():
    s = load_settings()
    assert s["health"]["frozen"]["ceiling_aware"] is False and s["limits"]["learned_step_cap"] is False


def test_saturated_humidity_frozen_is_hard_today_and_soft_with_the_remedy():
    hist = frozen_history(30)                                   # 30 h at exactly 100 %: beyond twice the 10 h learned limit
    off = check_frozen(hist, "humidity_pct", load_settings(), CAD, limits_with())
    s_on = load_settings(); s_on["health"]["frozen"]["ceiling_aware"] = True
    on = check_frozen(hist, "humidity_pct", s_on, CAD, limits_with())
    assert off.flagged and off.severity == "hard"
    assert on.flagged and on.severity == "soft" and "ceiling" in on.reason


def test_temperature_frozen_while_saturated_is_soft_only_with_the_remedy():
    hist = frozen_history(30)
    s_on = load_settings(); s_on["health"]["frozen"]["ceiling_aware"] = True
    assert check_frozen(hist, "temperature_c", load_settings(), CAD, limits_with()).severity == "hard"
    assert check_frozen(hist, "temperature_c", s_on, CAD, limits_with()).severity == "soft"


def test_the_remedy_does_not_soften_a_stuck_barometer_or_a_stuck_dry_humidity_sensor():
    s_on = load_settings(); s_on["health"]["frozen"]["ceiling_aware"] = True
    assert check_frozen(frozen_history(30), "pressure_hpa", s_on, CAD, limits_with()).severity == "hard"      # even while RH is 100 %
    assert check_frozen(frozen_history(30, rh=62.0), "humidity_pct", s_on, CAD, limits_with()).severity == "hard"
    assert check_frozen(frozen_history(30, rh=62.0), "temperature_c", s_on, CAD, limits_with()).severity == "hard"


def test_the_remedy_needs_the_whole_window_saturated():
    s_on = load_settings(); s_on["health"]["frozen"]["ceiling_aware"] = True
    hist = make_history(31, cadence=CAD, t=lambda i: 26.0, p=lambda i: 1000.0 + 0.1 * i, rh=lambda i: 80.0 if i == 26 else 100.0)   # one unsaturated reading inside the 10 h window
    assert check_frozen(hist, "temperature_c", s_on, CAD, limits_with()).severity == "hard"


# ---- remedy 2 --------------------------------------------------------------------------------------------------
def jump_history(delta, minutes=CAD):
    return [make_reading(0, t=20.0), make_reading(minutes, t=20.0 + delta)]


def test_step_cap_is_the_configured_one_by_default_and_a_learned_one_raises_it():
    s_off = load_settings()
    s_on = load_settings(); s_on["limits"]["learned_step_cap"] = True
    lim = limits_with(step_cap=14.0)
    assert check_step(jump_history(12.0), "temperature_c", s_off, CAD, lim).flagged            # configured cap 10 C
    assert not check_step(jump_history(12.0), "temperature_c", s_on, CAD, lim).flagged         # learned cap 14 C
    assert check_step(jump_history(15.0), "temperature_c", s_on, CAD, lim).flagged             # still a jump beyond what this station does


def test_a_learned_cap_below_the_configured_one_changes_nothing():
    s_on = load_settings(); s_on["limits"]["learned_step_cap"] = True
    lim = limits_with(step_cap=3.0)
    assert not check_step(jump_history(9.0), "temperature_c", s_on, CAD, lim).flagged          # 9 C < configured 10 C cap
    assert check_step(jump_history(11.0), "temperature_c", s_on, CAD, lim).flagged


def test_no_limits_no_change():
    s_on = load_settings(); s_on["limits"]["learned_step_cap"] = True
    assert check_step(jump_history(12.0), "temperature_c", s_on, CAD, None).flagged


def test_fit_limits_learns_the_step_cap_from_the_stations_own_history():
    series = rounded_series(seed=3)
    lim = fit_limits(series, load_settings(), CAD)
    cap = lim.step_cap("temperature_c")
    d = np.abs(np.diff([r.temperature_c for r in series]))
    assert cap == pytest.approx(float(np.quantile(d, 0.999)) * 1.1)
    assert cap < 10.0                                                                # a mild station: the configured cap still governs


def test_learned_step_cap_needs_enough_samples_and_skips_gaps():
    series = rounded_series(n=100)
    assert learned_step_cap(series, "temperature_c", 180.0, 0.999, 1.1, 500) is None
    short = [make_reading(0, t=20.0), make_reading(60, t=21.0), make_reading(600, t=40.0)]         # the 540-min pair is a gap
    assert learned_step_cap(short * 1, "temperature_c", 180.0, 0.5, 1.0, 1) == pytest.approx(1.0 * 1.0)


def test_old_limits_files_without_a_step_cap_still_load(tmp_path):
    import json
    lim = limits_with()
    p = tmp_path / "l.json"
    lim.save(p)
    d = json.loads(p.read_text())
    for c in d["channels"].values():
        c.pop("step_cap")
    p.write_text(json.dumps(d))
    assert StationLimits.load(p).step_cap("temperature_c") is None
