"""The ESP32's L0 logic, run for real on the laptop.

firmware/node/atmos_l0.h is plain C++ (no Arduino headers), so g++ builds it here. These tests build the SAME code
that node.ino includes and check it against the Python implementation (atmos/physics.py, simnode.py) on thousands
of random and edge-case inputs. node.ino itself is type-checked against stand-ins for the Arduino libraries.

What this does NOT prove: that the sketch compiles with the real ESP32 toolchain, or that it runs on hardware.
The stand-ins (firmware/tests/stubs) only let g++ check names and types.
"""
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

import simnode
from atmos.config import load_settings
from atmos.physics import dew_point_c
from atmos.schema import CHANNELS

ROOT = Path(__file__).resolve().parent.parent
NODE = ROOT / "firmware" / "node"
TESTS = ROOT / "firmware" / "tests"
GXX = shutil.which("g++") or shutil.which("clang++")

pytestmark = pytest.mark.skipif(GXX is None, reason="no C++ compiler on this machine")


@pytest.fixture(scope="module")
def parity_bin(tmp_path_factory):
    out = tmp_path_factory.mktemp("edge") / "l0_parity"
    r = subprocess.run([GXX, "-std=c++11", "-O1", "-Wall", "-Wextra", "-Werror", f"-I{NODE}", str(TESTS / "l0_parity.cpp"),
                        "-o", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def run_bin(binary, text: str) -> list[str]:
    r = subprocess.run([str(binary)], input=text, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()


def test_the_sketch_type_checks_against_arduino_stand_ins(tmp_path):
    shutil.copy(NODE / "secrets.example.h", tmp_path / "secrets.h")
    r = subprocess.run([GXX, "-std=gnu++11", "-fsyntax-only", "-x", "c++", "-Wall", "-Wno-unused-variable",
                        f"-I{TESTS / 'stubs'}", f"-I{tmp_path}", f"-I{NODE}", str(NODE / "node.ino")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_sketch_also_type_checks_with_the_api_key_switched_on(tmp_path):
    shutil.copy(NODE / "secrets.example.h", tmp_path / "secrets.h")
    r = subprocess.run([GXX, "-std=gnu++11", "-fsyntax-only", "-x", "c++", "-Wall", "-Wno-unused-variable", '-DAPI_KEY="k"',
                        f"-I{TESTS / 'stubs'}", f"-I{tmp_path}", f"-I{NODE}", str(NODE / "node.ino")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_dew_point_matches_python(parity_bin):
    rng = np.random.default_rng(1)
    cases = [(float(t), float(rh)) for t, rh in zip(rng.uniform(-40, 55, 4000), rng.uniform(0.5, 100, 4000))]
    out = run_bin(parity_bin, "\n".join(f"D {t!r} {rh!r}" for t, rh in cases))
    worst = max(abs(float(o) - dew_point_c(t, rh)) for o, (t, rh) in zip(out, cases))
    assert worst < 2e-3, worst                    # float32 on the device vs float64 here


def _minute_text(samples):
    rows = "\n".join(" ".join("nan" if (v is None or (isinstance(v, float) and math.isnan(v))) else repr(float(v))
                             for v in s) for s in samples)
    return f"M {len(samples)}\n{rows}"


def _parse(line):
    f = line.split()
    present = [bool(int(x)) for x in f[:3]]
    values = {ch: (float(f[3 + i]) if present[i] else None) for i, ch in enumerate(CHANNELS)}
    bits = int(f[6])
    flags = set()
    for i, ch in enumerate(CHANNELS):
        if bits & (1 << i):
            flags.add(f"range:{ch}")
        if bits & (1 << (3 + i)):
            flags.add(f"few_valid:{ch}")
        if bits & (1 << (7 + i)):
            flags.add(f"frozen:{ch}")
    if bits & (1 << 6):
        flags.add("dew_point")
    return values, flags


def _random_minute(rng, kind):
    n = 60
    base = np.array([rng.uniform(-10, 45), rng.uniform(950, 1030), rng.uniform(20, 95)])
    s = base + rng.normal(0, [0.2, 0.1, 1.0], (n, 3))
    s = [list(map(float, r)) for r in s]
    if kind == "nan_burst":
        for i in rng.choice(n, 40, replace=False):
            s[i][int(rng.integers(3))] = float("nan")
    elif kind == "out_of_range":
        for i in rng.choice(n, 5, replace=False):
            s[i][int(rng.integers(3))] = float(rng.choice([-120.0, 300.0 - 1, 1100.5, 100.5, 255.0]))
    elif kind == "dew_point":
        s = [[t, p, 100.0] for t, p, _ in s]
        s = [[t, p, min(100.0, rh + 5) if False else 100.0] for t, p, rh in s]
    elif kind == "dead":
        s = [[float("nan")] * 3 for _ in range(n)]
    return s


def test_minute_logic_matches_python_on_random_minutes(parity_bin):
    settings = load_settings()
    rng = np.random.default_rng(7)
    kinds = ["clean", "nan_burst", "out_of_range", "dew_point", "dead"] * 40
    minutes = [_random_minute(rng, k) for k in kinds]
    out = run_bin(parity_bin, "R\n" + "\n".join(_minute_text(m) for m in minutes))
    assert len(out) == len(minutes)
    tracker = simnode.FrozenTracker(settings["node"]["frozen_minutes"])
    for m, line in zip(minutes, out):
        cpp_values, cpp_flags = _parse(line)
        py_values, py_flags = simnode.aggregate_minute(m, settings, tracker)
        assert set(py_flags) == cpp_flags, (py_flags, cpp_flags)
        for ch in CHANNELS:
            if py_values[ch] is None:
                assert cpp_values[ch] is None
            else:
                assert cpp_values[ch] == pytest.approx(py_values[ch], abs=2e-3)


def test_frozen_counter_matches_python_across_minutes(parity_bin):
    """A sensor that repeats the same minute mean: flagged from the `frozen_minutes`-th identical minute on."""
    settings = load_settings()
    n = settings["node"]["frozen_minutes"]
    stuck = [[21.5, 1000.0, 55.0]] * 60
    wobble = [[21.5 + 0.01 * (i % 7), 1000.0 + 0.02 * (i % 5), 55.0 + 0.1 * (i % 3)] for i in range(60)]
    minutes = [stuck] * (n + 5) + [wobble]
    out = run_bin(parity_bin, "R\n" + "\n".join(_minute_text(m) for m in minutes))
    tracker = simnode.FrozenTracker(n)
    py = [simnode.aggregate_minute(m, settings, tracker)[1] for m in minutes]
    cpp = [_parse(line)[1] for line in out]
    assert [set(x) for x in py] == cpp
    first = next(i for i, f in enumerate(cpp) if "frozen:temperature_c" in f)
    assert first == n - 1                                     # the n-th identical minute
    assert "frozen:temperature_c" not in cpp[-1]              # the sensor moved: run reset


def test_a_missing_minute_breaks_the_frozen_run(parity_bin):
    settings = load_settings()
    n = settings["node"]["frozen_minutes"]
    stuck = [[21.5, 1000.0, 55.0]] * 60
    dead = [[float("nan")] * 3] * 60
    minutes = [stuck] * (n - 1) + [dead] + [stuck] * 3
    out = run_bin(parity_bin, "R\n" + "\n".join(_minute_text(m) for m in minutes))
    assert all("frozen:temperature_c" not in _parse(line)[1] for line in out)


def test_config_h_carries_the_frozen_setting(settings):
    assert f"#define L0_FROZEN_MINUTES {settings['node']['frozen_minutes']}" in (NODE / "config.h").read_text()
