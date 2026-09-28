"""Static checks on firmware/node. The sketch is NOT compiled here (no Arduino toolchain), so these tests
only guard the things that can silently drift: the generated limits, the JSON keys, the flag names."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

from atmos.schema import Reading

NODE = Path(__file__).resolve().parent.parent / "firmware" / "node"
INO = (NODE / "node.ino").read_text()


def test_config_h_is_in_sync_with_settings():
    r = subprocess.run([sys.executable, str(NODE / "gen_config.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_config_h_has_every_limit_the_sketch_uses(settings):
    text = (NODE / "config.h").read_text()
    lo, hi = settings["physics"]["ranges"]["temperature_c"]
    assert f"L0_TEMPERATURE_MIN_C {lo!r}f" in text and f"L0_TEMPERATURE_MAX_C {hi!r}f" in text
    assert f"MIN_VALID_SAMPLES {settings['node']['min_valid_samples']}" in text
    for macro in set(re.findall(r"\b(?:L0_[A-Z_]+|SAMPLE_INTERVAL_MS|AGGREGATE_SECONDS|MIN_VALID_SAMPLES|BUFFER_SLOTS|POST_TIMEOUT_MS)\b", INO)):
        assert f"#define {macro} " in text, f"{macro} is used in node.ino but not defined in config.h"


def test_generator_changes_when_settings_change(settings):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_config", NODE / "gen_config.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    settings["physics"]["ranges"]["temperature_c"] = [-50.0, 55.0]
    assert "L0_TEMPERATURE_MIN_C -50.0f" in gen.render(settings)


def test_no_physics_limits_are_hard_coded_in_the_sketch():
    body = re.sub(r"//.*", "", INO)
    for number in ("-90", "1100", "300.0", "0.5f", "MIN_VALID_SAMPLES = ", "= 30"):      # limits and counts live in config.h
        assert number not in body


def test_sketch_sends_the_fields_the_api_expects():
    keys = set(re.findall(r'\\"([a-z_]+)\\":', INO))
    assert keys == {"station_id", "timestamp", "temperature_c", "pressure_hpa", "humidity_pct", "device_flags"}
    assert keys <= set(Reading.model_fields)
    assert "API_URL" in INO and "Content-Type" in INO and "http.POST" in INO


def test_sketch_flag_names_match_simnode():
    assert "range:%s" in INO and "few_valid:%s" in INO and 'dew_point\\"' in INO
    import simnode
    from atmos.config import load_settings
    _, flags = simnode.aggregate_minute([(0, 0, 0)] * 3, load_settings())
    assert {f.split(":")[0] for f in flags} <= {"range", "few_valid", "dew_point"}


def test_sketch_reports_missing_values_as_null_and_uses_utc():
    assert 'snprintf(field[c], sizeof(field[c]), "null")' in INO
    assert "gmtime_r" in INO and "configTime(0, 0" in INO


def test_sketch_braces_and_parentheses_balance():
    body = re.sub(r'//.*|"(\\.|[^"\\])*"', "", INO)
    assert body.count("{") == body.count("}") and body.count("(") == body.count(")")


def test_sketch_has_setup_and_loop_and_includes():
    for needle in ("void setup()", "void loop()", '#include "config.h"', '#include "secrets.h"', "Adafruit_BME280"):
        assert needle in INO


def test_secrets_are_not_committed_but_an_example_exists():
    example = (NODE / "secrets.example.h").read_text()
    for macro in ("WIFI_SSID", "WIFI_PASSWORD", "API_URL", "STATION_ID"):
        assert f"#define {macro} " in example and macro in INO
    assert not (NODE / "secrets.h").exists() or "secrets.h" in (NODE.parent.parent / ".gitignore").read_text()
    assert "firmware/node/secrets.h" in (NODE.parent.parent / ".gitignore").read_text().splitlines()
