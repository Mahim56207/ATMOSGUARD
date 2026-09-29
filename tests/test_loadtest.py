"""loadtest.py must exercise every layer of the shipped pipeline, or its speed figures describe a smaller system."""
import loadtest
from atmos.config import load_settings
from atmos.fusion import Pipeline


def test_fleet_has_every_per_station_model_and_the_pipeline_uses_them():
    s = load_settings()
    tables, models, limits, mahal, streams, stations = loadtest.build_fleet(s, 2, train_days=6)
    assert set(tables) == set(models) == set(limits) == set(mahal) == set(streams) == set(stations)
    pipe = Pipeline(s, stations, tables, models, limits, mahal)
    sid = next(iter(streams))
    assert set(pipe.mahalanobis) == set(tables)
    result = pipe.process(streams[sid][0])
    assert result.verdict in {"VALID", "WEATHER", "SUSPECT", "FAULT"}
    sizes = loadtest.storage_per_station(tables, models, limits, mahal)
    assert sizes["mahalanobis_kb"] > 0 and sizes["total_kb"] >= sizes["mahalanobis_kb"]
