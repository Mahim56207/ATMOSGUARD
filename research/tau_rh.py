"""tau_RH: does a slower humidity response show up, and where does the idea stop working?

This is RESEARCH, not part of the live pipeline, and nothing here is claimed as a working fault detector.
The physics of a slower humidity response (fouled or covered element) is established; the audit found no
operational AWS QC system using it as a health metric. What is not established is whether it can be measured from
what real networks send. This file gives the team two things:

  1. `bench`  : the analysis for the two-sensor bench experiment (build guide T4 / W10). Feed it the CSV your
                two identical sensors logged (one clean, one covered). It finds the humidity transitions, measures
                the 63 % response time of each sensor, checks that the two sensors' temperatures stayed together
                (a thermal-lag artefact would ruin the result), and reports covered vs clean with a rank test.
  2. `study`  : a simulation of a first-order sensor pair in a fluctuating atmosphere, asking how well the RELATIVE
                lag between two co-located sensors can be recovered at 1 Hz, 1-minute and 15-minute averaging.
                It is the honest answer to "can we do this from operational data?": see the printed table.
  3. `selftest`: the bench analysis run on simulated data with a known answer.

Usage:
    python research/tau_rh.py study
    python research/tau_rh.py selftest
    python research/tau_rh.py bench logs.csv          # columns: t_s, rh_clean, rh_covered, temp_clean, temp_covered

All simulated results are simulations: they show what the method can and cannot do under the stated model, not what a
particular real sensor does.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.signal import lfilter
from scipy.stats import mannwhitneyu

FRACTION = 1.0 - 1.0 / np.e         # 63.2 % of the total change


# ------------------------------------------------------------------------------------------------ bench analysis
def response_time_63(t: np.ndarray, y: np.ndarray, t_step: float, settle_s: float, pre_s: float = 20.0
                     ) -> Optional[float]:
    """Seconds after `t_step` until y has covered 63.2 % of its total change. The starting level is the mean over the
    `pre_s` seconds before the step, the final level is the mean of the last 20 % of the `settle_s` seconds after."""
    before = y[(t >= t_step - pre_s) & (t < t_step)]
    after = (t >= t_step) & (t < t_step + settle_s)
    if before.size < 3 or after.sum() < 10:
        return None
    ta, ya = t[after], y[after]
    final = float(np.mean(ya[int(0.8 * ya.size):]))
    start = float(np.mean(before))
    total = final - start
    if abs(total) < 3.0:                       # less than 3 % RH of change: not a usable transition
        return None
    target = start + FRACTION * total
    crossed = np.nonzero((ya - target) * np.sign(total) >= 0)[0]
    return None if crossed.size == 0 else float(ta[crossed[0]] - t_step)


def refine_onset(t: np.ndarray, rh: np.ndarray, t_detect: float, window_s: float) -> float:
    """The detector below fires up to `window_s` BEFORE the humidity actually moves (it compares two points a window
    apart). The onset is the time of the steepest rise (3-sample smoothing) in the following two windows."""
    sel = (t >= t_detect) & (t < t_detect + 2 * window_s)
    if sel.sum() < 5:
        return t_detect
    slope = np.abs(np.convolve(np.diff(rh[sel]), np.ones(3) / 3.0, mode="same"))
    return float(t[sel][int(np.argmax(slope))])


def find_transitions(t: np.ndarray, rh: np.ndarray, min_change: float = 10.0, window_s: float = 60.0) -> list[float]:
    """Onset times where the reference sensor's humidity moved by at least `min_change` % within `window_s` (a box
    was swapped)."""
    dt = float(np.median(np.diff(t)))
    k = max(1, int(window_s / dt))
    change = rh[k:] - rh[:-k]
    idx = np.nonzero(np.abs(change) >= min_change)[0]
    out: list[float] = []
    last = -1e18
    for i in idx:
        if t[i] - last > 3 * window_s:          # one transition per burst
            out.append(refine_onset(t, rh, float(t[i]), window_s))
        last = t[i]
    return out


def analyse_bench(t, rh_clean, rh_cover, temp_clean, temp_cover, settle_s: float = 300.0,
                  max_temp_gap_c: float = 0.2) -> dict:
    steps = find_transitions(t, rh_clean)
    rows = []
    for ts in steps:
        a = response_time_63(t, rh_clean, ts, settle_s)
        b = response_time_63(t, rh_cover, ts, settle_s)
        window = (t >= ts - 20) & (t < ts + settle_s)
        gap = float(np.max(np.abs(temp_clean[window] - temp_cover[window]))) if window.any() else float("nan")
        rows.append({"t_step_s": ts, "tau63_clean_s": a, "tau63_covered_s": b, "max_temp_gap_c": gap,
                     "usable": a is not None and b is not None and gap <= max_temp_gap_c})
    ok = [r for r in rows if r["usable"]]
    out = {"transitions_found": len(rows), "usable": len(ok), "rows": rows}
    if len(ok) >= 3:
        a = np.array([r["tau63_clean_s"] for r in ok])
        b = np.array([r["tau63_covered_s"] for r in ok])
        out.update(median_clean_s=float(np.median(a)), median_covered_s=float(np.median(b)),
                   ratio=float(np.median(b) / np.median(a)),
                   p_value=float(mannwhitneyu(b, a, alternative="greater").pvalue))
    return out


# ------------------------------------------------------------------------------------------------ simulation
def first_order(x: np.ndarray, tau_s: float, dt: float) -> np.ndarray:
    """A first-order sensor: y' = (x - y) / tau, exact for an input that is constant between samples.
    The sensor starts at the first input value."""
    a = float(np.exp(-dt / tau_s))
    return lfilter([1 - a], [1, -a], x - x[0]) + x[0]


def ou_process(n: int, dt: float, corr_s: float, sigma: float, rng: np.random.Generator, mean: float = 60.0) -> np.ndarray:
    """Ambient humidity: an Ornstein-Uhlenbeck process (correlation time corr_s, spread sigma). Fluctuates like
    a real boundary layer would over minutes, not like white noise."""
    a = float(np.exp(-dt / corr_s))
    e = rng.normal(0, sigma * np.sqrt(1 - a * a), n)
    return mean + lfilter([1.0], [1.0, -a], e)


def simulate_pair(tau_clean: float, tau_cover: float, seconds: int, rng: np.random.Generator, noise: float = 0.15,
                  corr_s: float = 300.0, sigma: float = 6.0, boxes: bool = False) -> dict:
    dt = 1.0
    n = int(seconds / dt)
    t = np.arange(n) * dt
    ambient = ou_process(n, dt, corr_s, sigma, rng)
    if boxes:                                    # the bench: alternate between dry (~15 %) and salt (~75 %) every 600 s
        ambient = np.where((t // 600) % 2 == 0, 15.0, 75.0)
    a = first_order(ambient, tau_clean, dt) + rng.normal(0, noise, n)
    b = first_order(ambient, tau_cover, dt) + rng.normal(0, noise, n)
    return {"t": t, "ambient": ambient, "clean": a, "covered": b}


def average(x: np.ndarray, k: int) -> np.ndarray:
    n = (len(x) // k) * k
    return x[:n].reshape(-1, k).mean(axis=1)


def relative_lag_estimate(clean: np.ndarray, covered: np.ndarray, dt: float, tau_max_s: float = 900.0,
                          min_gain: float = 0.02) -> tuple[Optional[float], float]:
    """The first-order time constant that, applied to `clean`, best reproduces `covered` (free gain and offset).
    Two co-located sensors see the same air, so their difference is not confounded by the weather: this is what a
    pair can identify and a single sensor cannot.
    Returns (tau, gain). `gain` is the share of the residual variance the lag removes compared with no lag. If it is
    below `min_gain` the lag is NOT identifiable at this resolution and tau is None: the loss is flat, and any number
    would be noise."""
    def loss(tau: float) -> float:
        lag = first_order(clean, max(tau, 1e-3), dt) if tau > 1e-3 else clean
        A = np.vstack([lag, np.ones_like(lag)]).T
        coef, *_ = np.linalg.lstsq(A, covered, rcond=None)
        r = covered - A @ coef
        return float(np.mean(r * r))
    base = loss(0.0)
    res = minimize_scalar(loss, bounds=(1e-3, tau_max_s), method="bounded", options={"xatol": 1e-2})
    gain = 1.0 - float(res.fun) / base if base > 0 else 0.0
    return (float(res.x) if gain >= min_gain else None), gain


def study(seed: int = 42, hours: int = 6, repeats: int = 20) -> list[dict]:
    """How well is the RELATIVE lag between a clean sensor (tau 10 s) and a fouled one recovered, by data resolution?
    At the low frequencies of real weather, two first-order sensors differ by a lag of (tau_fouled - tau_clean)."""
    rng = np.random.default_rng(seed)
    rows = []
    tau_clean = 10.0
    for tau_cover in (20.0, 40.0, 90.0, 240.0):
        true_rel = tau_cover - tau_clean
        for label, k in (("1 s", 1), ("1 min mean", 60), ("15 min mean", 900)):
            est = []
            for _ in range(repeats):
                s = simulate_pair(tau_clean, tau_cover, hours * 3600, rng)
                a, b = average(s["clean"], k), average(s["covered"], k)
                tau, _gain = relative_lag_estimate(a, b, float(k))
                est.append(tau)
            got = [e for e in est if e is not None]
            ok = [e for e in got if abs(e - true_rel) <= 0.3 * true_rel]
            rows.append({"fouled_tau_s": tau_cover, "resolution": label, "true_relative_tau_s": round(true_rel, 1),
                         "identifiable": f"{100 * len(got) // repeats}%",
                         "within_30pct": f"{100 * len(ok) // repeats}%",
                         "median_estimate_s": round(float(np.median(got)), 1) if got else None})
    return rows


def print_study(rows: list[dict]) -> None:
    print("Recovering the relative response time of a fouled humidity sensor from a co-located clean one (simulation)")
    print("Clean sensor tau = 10 s. Ambient humidity fluctuates like an Ornstein-Uhlenbeck process (correlation 300 s, sd 6 %).")
    print("'lag found' = a lag explains at least 2 % of the difference between the sensors. 'correct' = the estimate is within 30 % of the truth.")
    print("A lag that is found but not correct is a coarse-resolution artefact: it looks like a result and is not one.")
    print(f"{'fouled tau':>11}{'resolution':>14}{'true relative lag':>19}{'lag found':>11}{'correct':>9}{'median estimate':>17}")
    for r in rows:
        est = "-" if r["median_estimate_s"] is None else f"{r['median_estimate_s']:.1f}s"
        print(f"{r['fouled_tau_s']:>10.0f}s{r['resolution']:>14}{r['true_relative_tau_s']:>18.1f}s"
              f"{r['identifiable']:>11}{r['within_30pct']:>9}{est:>17}")
    print("\nRead it as: at 1 Hz a co-located pair recovers the relative lag to about 10 %. At 1-minute means the estimate is")
    print("biased and only close for lags of several minutes. At 15-minute means (what many networks send) it is wrong")
    print("by hundreds of seconds. A single sensor cannot do this at any resolution, because its own lag cannot be")
    print("separated from the weather it is measuring.")


def selftest(seed: int = 3) -> dict:
    """The bench analysis on simulated dry/salt transitions where the answer is known (tau 10 s vs 40 s)."""
    rng = np.random.default_rng(seed)
    s = simulate_pair(10.0, 40.0, 7200, rng, boxes=True)
    temp = 24.0 + 0.02 * np.sin(s["t"] / 900.0)
    out = analyse_bench(s["t"], s["clean"], s["covered"], temp, temp + rng.normal(0, 0.03, temp.size))
    # for a first-order sensor the 63 % time IS tau
    out["true_clean_s"], out["true_covered_s"] = 10.0, 40.0
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="tau_RH research tools (not part of the live pipeline).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("study")
    sub.add_parser("selftest")
    b = sub.add_parser("bench")
    b.add_argument("csv")
    args = ap.parse_args(argv)
    if args.cmd == "study":
        print_study(study())
    elif args.cmd == "selftest":
        r = selftest()
        print(f"transitions found {r['transitions_found']}, usable {r['usable']}")
        print(f"clean median tau63 {r.get('median_clean_s', float('nan')):.1f} s (true {r['true_clean_s']}), "
              f"covered {r.get('median_covered_s', float('nan')):.1f} s (true {r['true_covered_s']}), "
              f"ratio {r.get('ratio', float('nan')):.2f}, p = {r.get('p_value', float('nan')):.3g}")
    else:
        d = np.genfromtxt(args.csv, delimiter=",", names=True)
        r = analyse_bench(d["t_s"], d["rh_clean"], d["rh_covered"], d["temp_clean"], d["temp_covered"])
        print(f"transitions found {r['transitions_found']}, usable {r['usable']} (temperature gap <= 0.2 C)")
        for row in r["rows"]:
            print(f"  t={row['t_step_s']:.0f}s  clean {row['tau63_clean_s']}  covered {row['tau63_covered_s']}  "
                  f"temp gap {row['max_temp_gap_c']:.2f} C  {'ok' if row['usable'] else 'NOT USABLE'}")
        if "ratio" in r:
            print(f"median tau63: clean {r['median_clean_s']:.1f} s, covered {r['median_covered_s']:.1f} s "
                  f"(ratio {r['ratio']:.2f}, one-sided rank test p = {r['p_value']:.3g}, n = {r['usable']})")
        else:
            print("fewer than 3 usable transitions: not enough to report a result.")
        print("Limits to print next to this number: cannot be separated from real humidity changes with ONE sensor in the field; "
              "blind to offset drift; needs ~1 Hz data, not 10-15 minute means.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
