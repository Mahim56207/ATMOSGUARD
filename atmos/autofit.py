"""Learn a NEW station from the first part of its own record, so a CSV somebody brings is judged with per-station models.

Without this an unknown station is judged with the fixed limits in config/settings.yaml, and on real, rounded station data those alarmed
on most clean samples (that is what the "without station-learned limits" row of the results shows). With it, the first part of the file
(half by default, at least two weeks) fits the same four things every committed station has: the month-by-hour normality table, the
Isolation Forest, the Mahalanobis model and the learned limits. The rest of the file is judged. The last two days of the learning part
are fed through the pipeline first (nothing is stored) so the history is not empty when judging starts.

Limits, stated: whatever is in the learning part is learned as normal, including a stuck sensor or a storm; a file shorter than two weeks
is not learned from; a file with under about two years has months without data, so the normality table is thin there. `evaluate_csv.py` is
the careful version (it cuts extreme-weather windows out of the learning part); this is the live one.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from .fusion import Pipeline
from .limits import fit_limits
from .mlmodel import IsolationModel, MahalanobisModel
from .normality import NormalityTable
from .schema import CHANNELS, Reading

MIN_DAYS = 14
MIN_ROWS = 300
WARM_DAYS = 2


@dataclass
class Learned:
    station_id: str
    trained_on: int
    judged: int
    cadence_minutes: float


def cadence_of(readings: Sequence[Reading]) -> float:
    gaps = [(b.timestamp - a.timestamp).total_seconds() / 60.0 for a, b in zip(readings, readings[1:])]
    gaps = [g for g in gaps if g > 0]
    return float(statistics.median(gaps)) if gaps else 60.0


def learn_stations(pipeline: Pipeline, readings: Sequence[Reading], settings: dict,
                   fraction: float = 0.5) -> tuple[list[Reading], list[Learned], list[str]]:
    """(readings still to be judged, what was learned, plain-English notes). Stations the pipeline already has models for are left alone."""
    by_station: dict[str, list[Reading]] = {}
    for r in sorted(readings, key=lambda r: r.timestamp):
        by_station.setdefault(r.station_id, []).append(r)
    judge: list[Reading] = []
    learned: list[Learned] = []
    notes: list[str] = []
    for sid, rows in by_station.items():
        if sid in pipeline.tables:
            judge += rows
            notes.append(f"{sid}: already has trained models; all {len(rows)} readings are judged.")
            continue
        cut = int(len(rows) * fraction)
        train = [r for r in rows[:cut] if all(getattr(r, ch) is not None for ch in CHANNELS)]
        span_days = (rows[cut - 1].timestamp - rows[0].timestamp).days if cut > 1 else 0
        if fraction <= 0 or len(train) < MIN_ROWS or span_days < MIN_DAYS:
            judge += rows
            notes.append(f"{sid}: not enough history to learn from ({len(train)} usable readings over {span_days} days in the learning part; "
                         f"needs {MIN_ROWS} readings over {MIN_DAYS} days). Judged with the fixed limits, which alarm too often on rounded real data.")
            continue
        cadence = cadence_of(train)
        table = NormalityTable.fit(train, settings)
        pipeline.tables[sid] = table
        pipeline.models[sid] = IsolationModel.fit(train, settings)
        pipeline.limits[sid] = fit_limits(train, settings, cadence)
        pipeline.mahalanobis[sid] = MahalanobisModel.fit(train, settings, table)
        pipeline.stations[sid] = {"cadence_minutes": cadence}
        warm_from = rows[cut - 1].timestamp - timedelta(days=WARM_DAYS)
        pipeline.warm_up([r for r in rows[:cut] if r.timestamp >= warm_from])
        rest = rows[cut:]
        judge += rest
        learned.append(Learned(sid, len(train), len(rest), cadence))
        notes.append(f"{sid}: learned from its first {len(train)} readings ({span_days} days); judging the other {len(rest)}. "
                     "Anything abnormal in the learning part was learned as normal.")
    judge.sort(key=lambda r: r.timestamp)
    return judge, learned, notes
