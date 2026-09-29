"""Check that a re-run reproduced an earlier evaluation: every number in the first result file must equal the second's.

    python compare_runs.py results/holdout_run1.json results/holdout_run2.json

Timings (`generated`, `fit_seconds`, `latency_ms`) are ignored because they depend on the machine. Keys that exist only in the
second file (a later run may add scores) are not compared; a key of the first that is missing or different in the second is a difference.
Exit status 0 when there are none.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

IGNORE = frozenset({"generated", "fit_seconds", "latency_ms"})


def compare(a: Any, b: Any, path: str = "", out: Optional[list] = None, count: Optional[list] = None) -> tuple[int, list[tuple[str, str]]]:
    """(number of values compared, list of (path, what differs))."""
    out = [] if out is None else out
    count = [0] if count is None else count
    if isinstance(a, dict):
        for k, v in a.items():
            if k in IGNORE:
                continue
            if not isinstance(b, dict) or k not in b:
                out.append((f"{path}/{k}", "missing in the second file"))
                continue
            compare(v, b[k], f"{path}/{k}", out, count)
    elif isinstance(a, list):
        if not isinstance(b, list) or len(a) != len(b):
            out.append((path, f"list length {len(a)} vs {len(b) if isinstance(b, list) else type(b).__name__}"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                compare(x, y, f"{path}[{i}]", out, count)
    else:
        count[0] += 1
        same = a == b or (isinstance(a, float) and isinstance(b, float) and abs(a - b) < 1e-9)
        if not same:
            out.append((path, f"{a!r} vs {b!r}"))
    return count[0], out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Compare two evaluate_real.py result files.")
    ap.add_argument("first", type=Path)
    ap.add_argument("second", type=Path)
    args = ap.parse_args(argv)
    n, diffs = compare(json.loads(args.first.read_text(encoding="utf-8")), json.loads(args.second.read_text(encoding="utf-8")))
    print(f"compared {n} values from {args.first.name} against {args.second.name}; differences: {len(diffs)}")
    for p, m in diffs[:40]:
        print("  ", p, m)
    return 1 if diffs else 0


if __name__ == "__main__":
    raise SystemExit(main())
