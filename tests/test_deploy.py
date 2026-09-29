"""Checks on the Docker files and requirements.txt. Docker is not installed here, so nothing is built:
these tests catch the mistakes that would only show up at build or start time."""
import ast
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
DOCKERFILE = (ROOT / "Dockerfile").read_text()


def test_compose_has_api_and_dashboard_with_the_right_ports_and_link():
    services = COMPOSE["services"]
    assert set(services) == {"api", "dashboard"}
    assert "8000:8000" in services["api"]["ports"] and "8501:8501" in services["dashboard"]["ports"]
    assert services["dashboard"]["environment"]["ATMOS_API_URL"] == "http://api:8000"
    assert services["dashboard"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert "healthcheck" in services["api"]


def test_compose_keeps_the_database_in_a_volume_and_mounts_config_data_models():
    api = COMPOSE["services"]["api"]
    assert api["environment"]["ATMOS_SQLITE_PATH"].startswith("/app/state/")
    assert "state:/app/state" in api["volumes"] and "state" in COMPOSE["volumes"]
    assert {"./config:/app/config", "./data:/app/data", "./models:/app/models"} <= set(api["volumes"])


def test_compose_commands_start_real_entry_points():
    assert COMPOSE["services"]["api"]["command"][:2] == ["uvicorn", "api:app"]
    dash = COMPOSE["services"]["dashboard"]["command"]
    assert dash[:3] == ["streamlit", "run", "dashboard.py"] and "0.0.0.0" in dash
    assert (ROOT / "dashboard.py").exists() and hasattr(__import__("api"), "app")


def test_dockerfile_installs_requirements_before_copying_the_code():
    assert DOCKERFILE.index("COPY requirements.txt") < DOCKERFILE.index("pip install") < DOCKERFILE.index("COPY . .")
    assert DOCKERFILE.startswith("FROM python:3.") and 'CMD ["uvicorn", "api:app"' in DOCKERFILE
    assert "EXPOSE 8000" in DOCKERFILE and "8501" in DOCKERFILE


def test_dockerignore_keeps_secrets_data_and_the_venv_out_of_the_image():
    lines = (ROOT / ".dockerignore").read_text().split()
    for item in (".venv", ".git", "data", "models", "firmware/node/secrets.h", "*.sqlite"):
        assert item in lines


def _imports():
    names = set()
    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def test_every_third_party_import_is_in_requirements():
    local = {p.stem for p in ROOT.glob("*.py")} | {p.name for p in ROOT.iterdir() if p.is_dir()}
    third_party = {n for n in _imports() if n not in sys.stdlib_module_names and n not in local}
    package_for = {"yaml": "pyyaml", "sklearn": "scikit-learn"}
    wanted = {package_for.get(n, n).lower() for n in third_party}
    wanted.discard("joblib")                               # installed together with scikit-learn
    have = {re.split(r"[<>=\[ ]", line.strip())[0].lower() for line in (ROOT / "requirements.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")}
    assert wanted <= have, f"missing from requirements.txt: {sorted(wanted - have)}"


def test_the_api_uses_the_database_path_from_the_environment(tmp_path, monkeypatch):
    from api import create_app
    from atmos.config import load_settings
    from fastapi.testclient import TestClient
    path = tmp_path / "state" / "x.sqlite"
    path.parent.mkdir()
    monkeypatch.setenv("ATMOS_SQLITE_PATH", str(path))
    c = TestClient(create_app(settings=load_settings()))
    c.post("/ingest", json={"station_id": "S1", "timestamp": "2026-01-01T00:00:00", "temperature_c": 20.0,
                            "pressure_hpa": 1000.0, "humidity_pct": 50.0})
    assert path.exists() and path.stat().st_size > 0


def test_database_path_rules(monkeypatch):
    import api
    monkeypatch.delenv("ATMOS_SQLITE_PATH", raising=False)
    assert api.database_path({"store": {"sqlite_path": "x.sqlite"}}) == str(api.REPO_ROOT / "x.sqlite")   # not the cwd
    assert api.database_path({"store": {"sqlite_path": "/data/x.sqlite"}}) == "/data/x.sqlite"
    assert api.database_path({"store": {"sqlite_path": ":memory:"}}) == ":memory:"
    monkeypatch.setenv("ATMOS_SQLITE_PATH", "/state/y.sqlite")
    assert api.database_path({"store": {"sqlite_path": "x.sqlite"}}) == "/state/y.sqlite"                 # env wins


def test_tests_never_touch_a_real_database_file():
    import os
    assert os.environ["ATMOS_SQLITE_PATH"] == ":memory:"
