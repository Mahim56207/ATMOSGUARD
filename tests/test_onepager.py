"""make_onepager.py: the one-page summary takes every number from the results, and says where the system fails."""
import make_figures as mf
import make_onepager as op


def test_rows_come_from_the_results_and_cover_every_split():
    aggs = mf.load_agg()
    rows = op.table_rows(aggs)
    assert [r["split"] for r in rows] == ["DEV", "Holdout in time", "Holdout in space", "Fresh stations", "Fresh 2", "Fresh 3"]
    dev = aggs["DEV"]["configs"]["full"]
    assert rows[0]["clean"] == 100 * dev["clean"]["alarm"] / dev["clean"]["n"]
    assert all(0 <= r["clean"] <= 100 and " of " in r["windows"] for r in rows)


def test_the_page_states_its_limits_and_the_windows_that_still_fail():
    text = op.build(mf.load_agg())
    for needle in ("Where it fails", "injected faults", "not run on hardware", "Textbook range", "AtmosGuard"):
        assert needle in text
    rows = op.table_rows(mf.load_agg())
    assert rows[2]["windows"] in text and rows[3]["windows"] in text           # the unseen-station counts are printed, not hidden
