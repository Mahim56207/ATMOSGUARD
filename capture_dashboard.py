"""Screenshots and a short video of the real dashboard running against the real API, for the slides and as a backup.

    python capture_dashboard.py                 # writes docs/screenshots/*.png and docs/demo/dashboard_walkthrough.webm

What it does: starts the API and the Streamlit dashboard on local ports with a throw-away database, replays a real cyclone
(Vardah, Chennai) through the pipeline, opens the dashboard in a headless Chromium, and photographs each tab. Then it arms a
frozen-pressure fault, replays the Delhi thunderstorm outflow through it, and photographs the verdicts the pipeline gave. The
video is the same session recorded. Needs Playwright with a Chromium (not a project requirement; the script says so if missing).
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

REPO = Path(__file__).resolve().parent
SHOTS = REPO / "docs" / "screenshots"
VIDEO = REPO / "docs" / "demo" / "dashboard_walkthrough.webm"
API_PORT, UI_PORT = 8765, 8766
API = f"http://127.0.0.1:{API_PORT}"
UI = f"http://127.0.0.1:{UI_PORT}"


def wait_for(url: str, seconds: float = 90) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            if httpx.get(url, timeout=3).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{url} did not come up")


def replay_and_wait(csv: str, limit: int) -> None:
    httpx.post(f"{API}/replay", json={"csv_path": csv, "speed": 0.0, "limit": limit}, timeout=30).raise_for_status()
    for _ in range(240):
        if httpx.get(f"{API}/status", timeout=10).json()["replay"]["state"] in ("done", "stopped"):
            return
        time.sleep(0.5)
    raise RuntimeError("replay did not finish")


def chromium() -> Optional[str]:
    return next((str(p) for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")), None)


def main() -> int:
    try:
        sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
    except ImportError:
        print("Playwright is not installed (pip install playwright; it is not a project requirement). Nothing captured.")
        return 1
    SHOTS.mkdir(parents=True, exist_ok=True)
    VIDEO.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="atmos_capture_"))
    env = {**os.environ, "ATMOS_SQLITE_PATH": str(tmp / "capture.sqlite"), "ATMOS_API_URL": API}
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "api:app", "--port", str(API_PORT), "--log-level", "warning"], cwd=REPO, env=env)
    ui = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "dashboard.py", "--server.port", str(UI_PORT), "--server.headless", "true",
                           "--browser.gatherUsageStats", "false"], cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for(f"{API}/status")
        wait_for(f"{UI}/_stcore/health")
        replay_and_wait("data/demo/vardah_MAA_2016-12.csv", 240)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chromium(), args=["--no-sandbox"])
            ctx = browser.new_context(viewport={"width": 1500, "height": 1450}, record_video_dir=str(tmp / "video"),
                                      record_video_size={"width": 1000, "height": 967})
            page = ctx.new_page()
            page.goto(UI)
            page.get_by_role("tab", name="Live monitor").wait_for(timeout=60000)
            page.wait_for_timeout(6000)
            page.screenshot(path=str(SHOTS / "01_live_monitor_cyclone_vardah.png"))

            page.get_by_role("tab", name="Control panel").click()
            page.wait_for_timeout(2500)
            page.screenshot(path=str(SHOTS / "02_control_panel.png"))

            # break the sensor: a frozen barometer at Delhi, then replay a real thunderstorm outflow through it
            httpx.post(f"{API}/inject", json={"station_id": "DEL", "fault_type": "frozen", "channel": "pressure_hpa", "samples": 60}, timeout=15).raise_for_status()
            replay_and_wait("data/demo/outflow_DEL_2021-04.csv", 200)
            page.reload()
            page.get_by_role("tab", name="Live monitor").wait_for(timeout=60000)
            page.locator('[data-testid="stSidebar"] [data-testid="stSelectbox"]').first.click()
            page.get_by_role("option", name="DEL").click()
            page.wait_for_timeout(6000)
            page.screenshot(path=str(SHOTS / "03_live_monitor_injected_fault_delhi.png"))

            page.get_by_role("tab", name="Evaluation").click()
            page.wait_for_timeout(3500)
            page.screenshot(path=str(SHOTS / "04_evaluation.png"), full_page=False)

            page.get_by_role("tab", name="How it decides").click()
            page.wait_for_timeout(2000)
            page.screenshot(path=str(SHOTS / "05_how_it_decides.png"))
            ctx.close()
            browser.close()
        vids = sorted((tmp / "video").glob("*.webm"))
        if vids:
            shutil.copy(vids[-1], VIDEO)
        print("wrote", ", ".join(sorted(p.name for p in SHOTS.glob("*.png"))), "and", VIDEO.name if vids else "(no video)")
        return 0
    finally:
        for proc in (ui, api):
            proc.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
