"""Tests for atmos/injector.py: each fault type, ground-truth log, seeds, raw data untouched."""
import json

import pytest

from atmos.injector import FAULT_TYPES, FaultSpec, inject, make_plan, write_log
from tests.conftest import synthetic_readings


@pytest.fixture
def clean():
    return synthetic_readings(days=5, cadence=15)


def _run(clean, settings, fault_type, channel="temperature_c", start=100):
    return inject(clean, settings, [FaultSpec(fault_type, channel, start)])


def _changed(clean, res, channel):
    return [i for i, (a, b) in enumerate(zip(clean, res.readings)) if getattr(a, channel) != getattr(b, channel)]


def test_input_readings_are_never_changed(clean, settings):
    before = [r.model_dump() for r in clean]
    inject(clean, settings, make_plan(clean, settings))
    assert [r.model_dump() for r in clean] == before


def test_frozen_holds_one_value(clean, settings):
    res = _run(clean, settings, "frozen")
    ev = res.events[0]
    vals = {res.readings[i].temperature_c for i in range(ev.start_index, ev.end_index + 1)}
    assert len(vals) == 1 and ev.end_index - ev.start_index + 1 == 8      # 120 min at 15-min cadence
    assert ev.params["held_value"] == clean[99].temperature_c


def test_spike_is_one_sample_and_right_size(clean, settings):
    res = _run(clean, settings, "spike")
    assert _changed(clean, res, "temperature_c") == [100]
    assert abs(res.readings[100].temperature_c - clean[100].temperature_c) == pytest.approx(8.0)


def test_step_shifts_whole_window_by_magnitude(clean, settings):
    res = _run(clean, settings, "step", channel="pressure_hpa")
    idx = _changed(clean, res, "pressure_hpa")
    assert idx == [100, 101, 102, 103]                                   # 60 min at 15-min cadence
    assert all(abs(res.readings[i].pressure_hpa - clean[i].pressure_hpa) == pytest.approx(5.0) for i in idx)


def test_drift_ramps_up_to_total_magnitude(clean, settings):
    res = _run(clean, settings, "drift", channel="humidity_pct")
    idx = _changed(clean, res, "humidity_pct")
    offs = [abs(res.readings[i].humidity_pct - clean[i].humidity_pct) for i in idx]
    assert len(idx) == 24 and offs == sorted(offs) and offs[-1] == pytest.approx(15.0)


def test_noise_adds_variation(clean, settings):
    res = _run(clean, settings, "noise")
    assert len(_changed(clean, res, "temperature_c")) == 4


def test_dropout_sets_none(clean, settings):
    res = _run(clean, settings, "dropout")
    assert [res.readings[i].temperature_c for i in (100, 101)] == [None, None]
    assert res.readings[102].temperature_c is not None                    # 30 min = 2 samples


def test_only_the_target_channel_changes(clean, settings):
    res = _run(clean, settings, "step", channel="temperature_c")
    assert _changed(clean, res, "pressure_hpa") == [] and _changed(clean, res, "humidity_pct") == []


def test_labels_and_event_log_match(clean, settings):
    res = inject(clean, settings, make_plan(clean, settings))
    for ev in res.events:
        assert all(res.labels[i] == ev.fault_type for i in range(ev.start_index, ev.end_index + 1))
    assert sum(l is not None for l in res.labels) == sum(e.end_index - e.start_index + 1 for e in res.events)


def test_plan_covers_every_fault_type_without_overlap(clean, settings):
    plan = make_plan(clean, settings)
    assert {p.fault_type for p in plan} == set(FAULT_TYPES)
    assert len(plan) == 6 * settings["injector"]["events_per_type"]
    inject(clean, settings, plan)                                          # would raise on overlap


def test_same_seed_gives_identical_result(clean, settings):
    a = inject(clean, settings, make_plan(clean, settings))
    b = inject(clean, settings, make_plan(clean, settings))
    assert [r.model_dump() for r in a.readings] == [r.model_dump() for r in b.readings]
    assert a.events == b.events


def test_different_seed_changes_plan(clean, settings):
    assert make_plan(clean, settings, seed=1) != make_plan(clean, settings, seed=2)


def test_overlapping_faults_are_rejected(clean, settings):
    with pytest.raises(ValueError):
        inject(clean, settings, [FaultSpec("step", "temperature_c", 100), FaultSpec("frozen", "pressure_hpa", 102)])


def test_unknown_fault_type_is_rejected(clean, settings):
    with pytest.raises(ValueError):
        inject(clean, settings, [FaultSpec("lightning", "temperature_c", 10)])


def test_log_is_written_as_json(clean, settings, tmp_path):
    res = _run(clean, settings, "step")
    write_log(res, tmp_path / "log.json")
    data = json.loads((tmp_path / "log.json").read_text())
    assert data[0]["fault_type"] == "step" and data[0]["channel"] == "temperature_c"


def test_bad_start_index_and_channel_are_rejected(clean, settings):
    with pytest.raises(ValueError):
        inject(clean, settings, [FaultSpec("step", "temperature_c", len(clean) + 5)])
    with pytest.raises(ValueError):
        inject(clean, settings, [FaultSpec("step", "wind_speed", 10)])
