# Demo runbook

A 7-minute main demo, a 5-minute cut, and what to do when something breaks. Everything runs from this repository with no
downloads and no internet.

## Cold start (do this at the venue, then again 30 minutes before)
```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn api:app --port 8000 &                             # loads the six trained stations from models/
streamlit run dashboard.py                                # http://localhost:8501
```
or `docker compose up --build` (run it once beforehand: it has not been built where this repository was made).
Check: the dashboard sidebar lists stations after the first replay; `GET http://localhost:8000/status` shows six stations
under `models_loaded`.

Optional live node: flash it (`docs/HARDWARE.md`), point `API_URL` at this laptop. No node? `python simnode.py --station BBI
--minutes 120` sends the same readings.

## The 7-minute demo
| Time | Do | Say |
|---|---|---|
| 0:00-0:40 | one slide or the Evaluation tab: the pressure crash of Cyclone Fani | "A cyclone and a broken barometer look the same on this chart. With only temperature, pressure and humidity we have to tell them apart." |
| 0:40-2:10 | **Control panel** -> replay `data/demo/fani_BBI_2019-05.csv`, speed 0 (fastest), then **Live monitor** for station BBI | "Real recorded data from Bhubaneswar airport, nothing injected. Pressure falls 30 hPa, humidity rises, temperature drops. All three move together, so it is escalated as WEATHER, not deleted. Notice: the station's own reports stop when the cyclone makes landfall. That gap is a notice, not a fault." |
| 2:10-3:10 | **Control panel** -> Arm fault: `frozen` on `pressure_hpa`, 30 readings; replay `yaas_BBI_2021-05.csv` (or arm during a live node stream) | "Now we break the barometer on demand. One channel stops changing while the other two keep moving. It is a FAULT, with the reason in plain English, and the estimated value sits beside the raw one; the raw value is never overwritten." |
| 3:10-4:10 | replay `outflow_CCU_2021-06.csv` | "This is a real thunderstorm outflow in Kolkata: temperature falls 12 C in three hours and humidity jumps by a third. A rule that says 'one channel jumped, the others are quiet' called this a fault. Real weather caught our own rule. We fixed it: 'quiet' now means the others actually did not move." |
| 4:10-5:10 | dashboard **Evaluation** tab, DEV headline | "Three separate numbers, never merged: false alarms on clean real data, what happens to real cyclones, heat waves and outflows, and detection of injected faults, which are labelled injected. The textbook rules baseline calls almost every real extreme-weather window a fault; ours does not." |
| 5:10-6:10 | Evaluation tab, HOLDOUT | "The holdout was sealed in time and in space and run once, with the protocol committed before. These are the numbers, including where they are worse." |
| 6:10-7:00 | Evaluation tab drift table; `docs/WHAT_WE_DO_NOT_CLAIM.md` | "Here is what we cannot do. A single station with no reference sees drifts of several times the service limit within weeks, not smaller ones. We report the smallest slope it can see. Humidity response time is research: here is the measured boundary." |

## The 5-minute cut
Fani replay, one armed fault, the outflow, and one slide with the DEV vs HOLDOUT headline and the "cannot do" list. Skip the rest.

## Things a judge may do, and what happens
- **"Inject something nasty."** Any of frozen, spike, level shift, drift, noise, dropout on any channel from the Control panel. Spikes and dropouts are caught at once; drift is caught by the health monitor over weeks, not minutes (say so).
- **"Replay a different event."** `data/real/dev/<STATION>.csv` has the whole 2016-2021 record for six stations; `POST /replay` with a `limit` plays any stretch. Sealed stations are not available to the replay by design.
- **"Use my data."** Any CSV with `timestamp, temperature_c, pressure_hpa, humidity_pct` (+ `station_id`) in `data/`. Without a trained station it runs on the physics and health layers only and says which layers had no model.

## When something breaks
| Problem | Do this |
|---|---|
| Wi-Fi blocks the ESP32 / no node | phone hotspot on 2.4 GHz, or `simnode.py`. The demo above does not need the node |
| No internet | nothing downloads at run time; everything is local |
| Dashboard crashes | play the backup video, restart with `streamlit run dashboard.py` |
| API port busy | `uvicorn api:app --port 8010` and set `ATMOS_API_URL=http://localhost:8010` |
| A judge disputes a claim | agree, name the prior art (`docs/NOVELTY_AND_PRIOR_ART.md`), point at what we added. Never defend a claim we cannot support |
| A number looks different from the report | the report was made from `results/*.json` with the commands in `docs/REPRODUCE.md`; say which run you are showing |

## Before you leave the house
- Backup video recorded with the venue network **off**, on the laptop itself (not the cloud).
- `data/`, `models/`, `results/` present in the clone. Charger, spare cable, phone hotspot tested.
- Rehearsed three times with a stopwatch; last 20 minutes empty.

## Assets you can use without running anything
- `docs/screenshots/` - the real dashboard in a browser, generated by `python capture_dashboard.py`: the Live monitor on Cyclone Vardah (WEATHER, not FAULT),
  the Control panel, the Network tab (every station, most urgent first), the Live monitor for Delhi with a frozen barometer armed on top of a real thunderstorm outflow (the red crosses are the injected fault,
  the purple triangles are the real weather), the Evaluation tab and How it decides.
- `docs/demo/dashboard_walkthrough.webm` - the same session as a video (a backup for the day the venue network fails; open it locally).
- `docs/demo/index.html` - the self-contained replay page (no server).
- `docs/figures/diagram_*.png` - the pipeline, the four verdicts and the order the evidence was produced in, for slides.
