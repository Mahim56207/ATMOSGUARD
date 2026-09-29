"""make_report.py: the technical report is assembled from parts and results, never typed by hand."""
import json
from pathlib import Path

import pytest

import make_report as mr
import make_summary as ms

REPO = Path(__file__).resolve().parents[1]


def test_demote_moves_headings_but_not_code_fences():
    md = "# Title\n\n## Part\ntext\n```\n# not a heading\n```\n### Sub"
    out = mr.demote(md, 1)
    assert "## Title" in out and "### Part" in out and "#### Sub" in out
    assert "# not a heading" in out and "## not a heading" not in out


def test_section_returns_the_body_up_to_the_next_section():
    md = "# T\n\n## A\nalpha\n\n## B (x)\nbeta\nmore\n\n## C\ngamma"
    assert mr.section(md, "B") == "beta\nmore"
    assert mr.section(md, "C") == "gamma"
    with pytest.raises(KeyError):
        mr.section(md, "Z")


def test_from_first_section_drops_title_and_intro():
    assert mr.from_first_section("# T\n\nintro\n\n## A\nbody").startswith("## A")


def test_every_part_the_report_quotes_exists():
    """A renamed heading in a source document must fail here, not silently vanish from the report."""
    novelty = (REPO / "docs" / "NOVELTY_AND_PRIOR_ART.md").read_text(encoding="utf-8")
    for h in ("1. What is standard (not ours)", "2. What we adapted (their idea, our engineering)", "3. What is ours",
              "5. The field on this problem statement (what judges will see side by side)",
              "6. Failures real data exposed, and what we did (kept on purpose)"):
        assert mr.section(novelty, h)
    protocol = (REPO / "config" / "protocol.md").read_text(encoding="utf-8")
    assert mr.section(protocol, "Tuning log (everything changed after looking at DEV, and why)")
    assert mr.section(protocol, "Amendment 1 (written after `holdout_run1` finished; the pipeline was not touched)")
    assert mr.section(protocol, "Amendment 2 (written before the FRESH stations were evaluated)")
    assert mr.section(protocol, "Amendment 2: outcome (written after `fresh_run1` finished; nothing was changed to make it come out this way)")
    assert mr.section((REPO / "docs" / "FAILURE_MODES.md").read_text(encoding="utf-8"), "What the system cannot see")
    repro = (REPO / "docs" / "REPRODUCE.md").read_text(encoding="utf-8")
    for h in ("1. Does it work? (about 1 minute)", "3. The evidence", "Determinism"):
        assert mr.section(repro, h)


@pytest.mark.skipif(not (REPO / "results" / "summary.json").exists(), reason="results/summary.json not built yet")
def test_report_builds_from_the_committed_summary():
    summary = json.loads((REPO / "results" / "summary.json").read_text(encoding="utf-8"))
    text = mr.build(summary)
    for heading in ("## Abstract", "## 1. Introduction", "## 3. Method", "## 4. Results", "## 5. What the holdout found",
                    "## 6. Limitations", "## 7. Related work", "## References"):
        assert heading in text
    assert "{{" not in text and "TODO" not in text
    assert "0.3%" in text or "3 of 98" in text     # the holdout finding is in the report, not hidden


def test_tradeoff_rows_name_each_systems_weakest_fault_type():
    phase = {
        "detection": {"rows": [
            {"configuration": "AtmosGuard (full)", "frozen": "100%", "spike": "97%", "noise burst": "78%"},
            {"configuration": "without timing layer", "frozen": "100%", "spike": "97%", "noise burst": "78%"},
            {"configuration": "baseline: Mahalanobis distance only", "frozen": "38%", "spike": "100%", "noise burst": "0%"},
            {"configuration": "(faults injected)", "frozen": "243", "spike": "243", "noise burst": "243"},
            {"configuration": "AtmosGuard: median minutes to the alarm", "frozen": "480", "spike": "0", "noise burst": "420"}]},
        "clean": {"rows": [{"configuration": "AtmosGuard (full)", "any alarm": "1.9%"},
                           {"configuration": "baseline: Mahalanobis distance only", "any alarm": "0.5%"}]},
        "extreme_weather": {"rows": [{"configuration": "AtmosGuard (full)", "windows with a FAULT": "0/30"},
                                     {"configuration": "baseline: Mahalanobis distance only", "windows with a FAULT": "0/30"}]},
    }
    rows = ms.tradeoff_rows(phase)
    assert [r["system"] for r in rows] == ["AtmosGuard (full)", "baseline: Mahalanobis distance only"]   # ablations and count rows left out
    assert rows[0]["weakest injected-fault type (fault raised the alarm)"] == "noise burst: 78%"
    assert rows[1]["weakest injected-fault type (fault raised the alarm)"] == "noise burst: 0%"
    assert rows[1]["false alarms on clean data"] == "0.5%"
