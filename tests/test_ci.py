"""The CI workflow must parse (a workflow that does not parse runs zero jobs and looks like a failure)."""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_is_valid_yaml_with_the_expected_steps():
    d = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = d["jobs"]["tests"]["steps"]
    runs = " ".join(s.get("run", "") for s in steps)
    assert "pytest" in runs and "gen_config.py --check" in runs and "evaluate.py --synthetic" in runs
    assert any(s.get("uses", "").startswith("actions/setup-python") and s["with"]["python-version"] == "3.13" for s in steps)
