import json

import compare_runs as cr


def test_identical_runs_have_no_differences_and_timings_are_ignored():
    a = {"generated": "t1", "stations": [{"station": "X", "fit_seconds": 1.0, "latency_ms": {"median": 5}, "clean": {"n": 10, "alarm": 2}}]}
    b = {"generated": "t2", "stations": [{"station": "X", "fit_seconds": 9.0, "latency_ms": {"median": 7}, "clean": {"n": 10, "alarm": 2}}]}
    n, diffs = cr.compare(a, b)
    assert diffs == [] and n == 3


def test_a_changed_number_a_missing_key_and_a_new_key():
    a = {"x": {"n": 10, "alarm": 2}, "y": [1, 2]}
    b = {"x": {"n": 10, "alarm": 3, "extra": 1}, "y": [1]}
    _, diffs = cr.compare(a, b)
    assert ("/x/alarm", "2 vs 3") in diffs
    assert any(p == "/y" for p, _ in diffs)
    assert not any("extra" in p for p, _ in diffs)          # a key only the second file has is not a difference

    _, diffs = cr.compare({"k": 1}, {})
    assert diffs == [("/k", "missing in the second file")]


def test_cli_exit_status(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"n": 1}))
    b.write_text(json.dumps({"n": 1}))
    assert cr.main([str(a), str(b)]) == 0
    b.write_text(json.dumps({"n": 2}))
    assert cr.main([str(a), str(b)]) == 1
