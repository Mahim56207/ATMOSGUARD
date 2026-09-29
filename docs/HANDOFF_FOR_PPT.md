# Handoff: everything that was done, what to submit, how to submit it

Written for the person who makes the final deck. The deck itself is deliberately not in this repository. Everything else is.
**Repository:** `github.com/Mahim56207/ATMOSGUARD`, branch **`dev`** (nothing was merged into `main` and no pull request was opened; download the branch as a ZIP from GitHub, or
`git clone -b dev https://github.com/Mahim56207/ATMOSGUARD.git`). Deadline you gave: 6:00 pm IST on 29 Sep 2026.

## 1. What AtmosGuard is, in three sentences
A monitor for one automatic weather station that uses only temperature, pressure and humidity. It decides for every reading whether it is `VALID`, real `WEATHER` (escalated, never deleted),
`SUSPECT` (review) or `FAULT` (broken sensor), with a plain-English reason and the raw value kept. Its evidence standard is the point: real data from 50 stations, sealed holdouts, rules registered before each test, baselines, and every failure kept on record.

## 2. What was built
| Part | Where |
|---|---|
| The pipeline: physics, station-learned health limits (frozen, step, spike, noise, CUSUM), station normality (month x hour), Isolation Forest + Mahalanobis, timing checks, fusion into four verdicts, health score and maintenance ticket, imputation | `atmos/` |
| API (FastAPI, 12 endpoints incl. `/ingest`, `/replay`, `/replay/upload`, `/inject`, `/fleet`, `/explain`, `/metrics`) and dashboard (Live monitor, Network, Control panel with break-the-sensor and bring-your-own-CSV, Evaluation, How it decides) | `api.py`, `dashboard.py` |
| A new station learns itself: the first half of an uploaded file trains its models | `atmos/autofit.py`; `refit.py` refits any station on a chosen stretch |
| ESP32 + BME280 node: sketch, portable L0 header, generated limits | `firmware/node/` |
| Optional peer layer: offsets and drift seen with three or more neighbours | `atmos/peers.py`, `evaluate_peers.py`, `docs/PEER_LAYER.md` |
| Evaluation on real data, protocol, amendments, lock files | `evaluate_real.py`, `config/protocol.md`, `data/*/.…_used` |
| Everything generated from the results: tables, figures, report, one-pager, offline demo | `make_summary.py`, `make_figures.py`, `make_report.py`, `make_onepager.py`, `make_offline_demo.py` |
| 470 automated tests, CI on every commit (green on the last one) | `tests/`, `.github/workflows/ci.yml` |

## 3. The evidence (copy numbers from `docs/JUDGE_QA.md`, block "Numbers to have in your head", never from memory)
| Split | Stations | Clean false alarms | Real extreme weather with a FAULT | Injected faults raised the alarm |
|---|---|---|---|---|
| DEV (tuned here, the optimistic one) | 6 Indian airports | 1.9 % | 0 of 30 windows | frozen 100, spike 98, level shift 97, noise 78, dropout 99, clock 97 (%) |
| Holdout, same stations, later years | 6 | 2.5 % | 0 of 38 | 100, 96, 98, 79, 100, 97 |
| Holdout, eight unseen stations (sealed in time and space, run once) | 8 | 2.9 % | 3 of 98 | 100, 90, 89, 67, 98, 84 |
| Fresh, twelve more unseen stations (Amendment 2) | 12 | 2.5 % | 3 of 139 | 99, 91, 80, 57, 98, 85 |
| **Fresh-2, twelve more (Amendment 3): 5 Indian airports + 7 Australian automatic weather stations at 0.1 resolution** | 12 | **9.3 %** (3.2 % airports, 13.6 % Australian AWS) | 4 of 134 (1 of 134 with the adopted remedy) | 100, 89, 91, 83, 93, 90 |
| **Fresh-3, twelve more (Amendment 4): 7 US automated stations reporting every 20 minutes at 0.1 C + 5 Australian AWS with irregular training years** | 12 | 9.7 % pooled: **2.7 % on the seven 20-minute stations**, 45.4 % on the five irregular Australian ones | 5 of 160 (3 of 103 on the 20-minute stations) | pooled 100, 84, 95, 100, 88, 96; 20-minute stations 100, 97, 99, 100, 99, 94 |

Also measured: baselines and an ablation on every split (textbook rules give 5-8 % false alarms and a FAULT in nearly every real extreme-weather window); agreement with NOAA's quality flags; slow-drift power;
cold start on day one; detection against fault size; speed (about 1 ms per reading on one core, 45 ms median through the real HTTP server). Injected faults are always labelled injected.

## 4. What was done in the last rounds (so you can say it)
1. **Docker built and run for real:** image built, your `docker-compose.yml` brought up (API health check green, dashboard up), a real cyclone (Vardah) replayed through the containerised API. It found and fixed a real crash (the API died if its state folder did not exist).
2. **The firmware sketch runs on a laptop simulator** (virtual clock, scripted sensor, dropping Wi-Fi, recording HTTP client); what it sends is accepted by the real API. Flags, null-not-zero for a dead sensor, the 30-minute offline queue and the clock guard are tested.
3. **Amendment 3, registered before the run:** two new remedies tested once on twelve sealed stations. By the rule written first, the **expected-change-aware step rule is adopted** (windows with a FAULT 4 to 1 of 134, nothing else moved) and the **sustained-offset check is rejected** (+1 point of level-shift detection against +5 required).
4. **A failure the new data exposed, reported, not hidden:** four Australian AWS had irregular reporting in their training years, so no noise limit could be learned and the fixed floor alarmed (33, 26, 21 and 8 % of clean samples). Refitted on the hourly years, false alarms fall to 2.6 % (post-hoc, not sealed evidence). The pipeline now prints an informational notice when limits do not fit, and `refit.py` is the one-command fix.
5. **The optional peer layer:** on two disjoint clusters of twelve Australian AWS, a 2 hPa offset is found in 91-96 % of trials within 21 days with neighbours, 0-4 % alone (2 C: 86-88 % against 1-9 %). It needs neighbours and was measured on injected faults. On 31 Indian airport stations, at the 600 km spacing India has, it finds a 2 hPa offset in 91 % of trials against 21 % alone (nothing gained on humidity).
6. Regression check: the full DEV evaluation with the shipped default reproduces the earlier numbers exactly (30,587 values, 0 differences). Documents, technical report (Markdown and Word), figures, one-pager, offline demo and dashboard screenshots were regenerated from the results.

## 5. What is NOT done, and the exact words for it
- **The fourth sealed set (Amendment 4) tested a limits warm-up for stations with irregular training records:** it cut false alarms at five such stations from 45.4 % to 1.8 % but cost 6 points of noise-burst detection, so by the rule written first it is **rejected** (available as `refit.py --complete`, not a default). It also gives the first sub-hourly evidence: seven real US automated stations reporting every 20 minutes, 2.7 % clean false alarms, 94-100 % of injected faults detected by type.
- **No real labelled faults** (none reachable): "detection is measured on injected faults, labelled injected".
- **No IMD record and no 1-15 minute data tested (the fastest real record is 20 minutes):** "IMD AWS records are not public; we tested Indian airport METAR and Australian Bureau of Meteorology automatic stations at 0.1 resolution, hourly; `evaluate_csv.py` runs the same evaluation on an IMD file in one command".
- **The ESP32 has not run on the chip** and no energy figure is measured: "the sketch runs against a simulator whose output the real API accepts; the checklist to flash it is `docs/HARDWARE_TEST_LOG.md`".
- **Small drift and constant offsets are invisible from one station;** the peer layer helps only with three or more neighbours.
- **One real extreme-weather window still gets a FAULT** (Thredbo, Oct 2023, humidity -48.9 % in two hours), and false alarms are 13.6 % (fresh-2) and 45 % (fresh-3) at stations whose training years were irregular unless refitted. Also: temperature pinned at 0 C for 9 hours in freezing rain gets a FAULT (two US stations, January 2024).
- **The Docker build was done in an environment whose proxy needed its CA injected;** on a normal machine nothing extra is needed. It is not part of CI.
Full list: `docs/WHAT_WE_DO_NOT_CLAIM.md`. Say these first; judges who find them themselves lose trust, judges who hear them gain it.

## 6. What to submit
The exact upload format and fields are set by the SIH portal and your nodal centre for this year: **read the current instructions there and follow them over this list.** A complete package that covers everything judges are documented to look at:
1. **The deck (PPT/PDF)** made from `docs/SLIDE_PLAN.md`, one row per slide with its message, asset and what to say. Figures and diagrams are in `docs/figures/` (PNG and SVG), screenshots in `docs/screenshots/`.
2. **The portal form text** from `docs/SUBMISSION_TEXT.md` (title, one line, problem, solution about 120 words, approach about 170 words, feasibility, impact, references, the exact novelty sentence, what we cannot do, the 30-second and 2-minute pitches). Numbers in it are generated from the results.
3. **The GitHub link** to the repository and branch above (make it public, or add the evaluators, if the portal needs to open it; the README is written to be the front page).
4. **The technical report:** `docs/TECHNICAL_REPORT.docx` (or the `.md`), about 2,200 lines with methods, protocol, every table and figure, limitations.
5. **The one-page summary:** `docs/AtmosGuard_one_page.pdf` (A4, checked to be one page).
6. **A demo video link.** A silent screen recording of the real dashboard is `docs/demo/dashboard_walkthrough.webm`; record your own narration over it following `docs/DEMO_RUNBOOK.md` and upload it (YouTube unlisted or Drive) if the portal takes a link.
7. **The offline demo** `docs/demo/index.html` (open in any browser, no server) as the backup for the room.

## 7. How to submit (a safe order)
1. Download the branch ZIP (or clone) and check it opens: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn api:app --port 8000 &` then `streamlit run dashboard.py`. `python -m pytest -q` should say 470 passed.
2. Run `docker compose up --build` once on the demo machine.
3. Make the deck; copy numbers only from `docs/JUDGE_QA.md`'s generated block and say which split each number comes from. Never merge the five numbers into one score.
4. Record the narrated video; keep a copy on the laptop with the network off.
5. Fill the portal with `docs/SUBMISSION_TEXT.md`, attach the deck, report, one-pager, video link and GitHub link.
6. Do not edit the numbers by hand anywhere; if a number must change, re-run `python make_summary.py …` (commands in `results/RUNS.md`).
7. Rehearse out loud with `docs/JUDGE_QA.md` and a stopwatch. The three certain questions are answered first in that file.

## 8. Lead with, and do not claim
**Lead with:** (1) false alarms on **real** cyclones and heat waves reported separately from injected faults; (2) holdouts sealed in time and space, run once, protocol and every remedy rule committed before the test; (3) "here is what we cannot do, with numbers".
**Do not claim:** that any technique is new (the novelty is the integration and the evidence: `docs/NOVELTY_AND_PRIOR_ART.md`); that injected-fault accuracy is real-world accuracy; that the humidity response-time idea works in the field; that the firmware has run on hardware; that the peer layer works without neighbours.

## 9. Things only your team can still do (about two hours of work)
Run Docker once; flash the ESP32 and fill `docs/HARDWARE_TEST_LOG.md` if you have a board; send `docs/IMD_DATA_REQUEST.md` to a mentor or IMD contact (and use `evaluate_csv.py` if a file arrives); record the narrated video; rehearse; make the deck. (The licence is done: Apache-2.0, see `LICENSE` and `NOTICE`. Check that SIH's own IP terms and every team member are happy with it.)
