"""Cold start: a brand-new station is usable on day one by borrowing a starter pattern, then learning its own.

A station's normality table needs a few years of history to have a well-filled cell for every month and hour, and its
learned limits need enough clean runs to be trustworthy. A new station has neither. The starter is built from OTHER
stations only (their tables, their limits): the nearest station, or the mean of the stations in the same climate zone.
As the station's own data grows, its own numbers take over, cell by cell:

    weight(own) = min(1, n_own_samples_in_the_cell / full_weight_samples)      for the normality table
    weight(own) = min(1, own_days / full_weight_days)                          for the learned limits

Nothing here reads a neighbour's LIVE data: the starter is a frozen table, so the single-station, neighbour-free
operating principle stays intact.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

from .limits import ChannelLimits, StationLimits
from .normality import NormalityTable
from .schema import CHANNELS


def _pool(tables: Sequence[NormalityTable], settings: dict) -> NormalityTable:
    """The mean pattern of several stations: mean of the cell means, pooled spread (within + between stations)."""
    cells: dict[str, dict[str, dict[str, float]]] = {}
    keys = {k for t in tables for k in t.cells}
    for key in keys:
        for ch in CHANNELS:
            parts = [t.cells[key][ch] for t in tables if key in t.cells and ch in t.cells[key]]
            if not parts:
                continue
            mean = sum(p["mean"] for p in parts) / len(parts)
            var = sum(p["std"] ** 2 + (p["mean"] - mean) ** 2 for p in parts) / len(parts)
            cells.setdefault(key, {})[ch] = {"mean": mean, "std": math.sqrt(var), "n": sum(p["n"] for p in parts)}
    return NormalityTable("starter", cells, settings)


def starter_table(others: Sequence[NormalityTable], settings: dict) -> NormalityTable:
    """The pattern a new station starts from: one table as it is, or the pooled pattern of several."""
    if not others:
        raise ValueError("a starter needs at least one other station")
    return others[0] if len(others) == 1 else _pool(others, settings)


def blend_tables(starter: NormalityTable, own: Optional[NormalityTable], settings: dict) -> NormalityTable:
    """Cell by cell: the starter where the station has no data of its own, the mixture of the two where it has a
    little, its own where it has enough. The spread of the mixture includes the disagreement between the two means."""
    full = settings["coldstart"]["full_weight_samples"]
    cells: dict[str, dict[str, dict[str, float]]] = {}
    for key in set(starter.cells) | set(own.cells if own else {}):
        for ch in CHANNELS:
            s = starter.cells.get(key, {}).get(ch)
            o = own.cells.get(key, {}).get(ch) if own else None
            if s is None and o is None:
                continue
            if o is None:
                cells.setdefault(key, {})[ch] = dict(s)
            elif s is None:
                cells.setdefault(key, {})[ch] = dict(o)
            else:
                w = min(1.0, o["n"] / full)
                mean = w * o["mean"] + (1 - w) * s["mean"]
                var = w * o["std"] ** 2 + (1 - w) * s["std"] ** 2 + w * (1 - w) * (o["mean"] - s["mean"]) ** 2
                cells.setdefault(key, {})[ch] = {"mean": mean, "std": math.sqrt(var), "n": o["n"]}
    return NormalityTable(own.station_id if own else "new", cells, settings)


def blend_limits(starter: Sequence[StationLimits], own: Optional[StationLimits], own_days: float, station_id: str,
                 cadence_minutes: float, settings: dict) -> StationLimits:
    """Learned limits for a station with `own_days` of clean history. Until it has `full_weight_days`, the limit is a
    mixture with the mean of the other stations' limits (a limit learned from a week of data is too small: it has not
    seen a long calm yet)."""
    full = settings["coldstart"]["full_weight_days"]
    w = min(1.0, max(0.0, own_days / full))
    out = StationLimits(station_id, cadence_minutes)
    for ch in CHANNELS:
        srcs = [s.channels[ch] for s in starter if ch in s.channels]
        frozen = [c.frozen_minutes for c in srcs if c.frozen_minutes]
        noise = [c.noise_std for c in srcs if c.noise_std]
        base_frozen = sum(frozen) / len(frozen) if frozen else None
        base_noise = sum(noise) / len(noise) if noise else None
        o = own.channels.get(ch) if own else None

        def mix(own_v: Optional[float], base: Optional[float]) -> Optional[float]:
            if own_v is None:
                return base
            if base is None:
                return own_v
            return w * own_v + (1 - w) * base
        res = next((c.resolution for c in srcs if c.resolution), None)
        out.channels[ch] = ChannelLimits(resolution=(o.resolution if o and o.resolution else res),
                                         frozen_minutes=mix(o.frozen_minutes if o else None, base_frozen),
                                         noise_std=mix(o.noise_std if o else None, base_noise),
                                         n_runs=o.n_runs if o else 0)
    return out


def nearest_stations(target: dict, candidates: dict[str, dict], k: int = 1) -> list[str]:
    """The k stations (by great-circle distance) to borrow from. `target` and `candidates` carry lat and lon."""
    def dist(a: dict, b: dict) -> float:
        p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
        dl = math.radians(b["lon"] - a["lon"])
        h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 6371.0 * 2 * math.asin(math.sqrt(h))
    return [sid for sid, _ in sorted(((sid, dist(target, c)) for sid, c in candidates.items()), key=lambda x: x[1])[:k]]


def same_zone(target: dict, candidates: dict[str, dict]) -> list[str]:
    return [sid for sid, c in candidates.items() if c.get("climate_zone") == target.get("climate_zone")]
