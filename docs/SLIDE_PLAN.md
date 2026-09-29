# Slide plan (content only: the deck itself is not made yet)

One row per slide: the message, what goes on it, where the asset lives, and what to say. Numbers are not typed here on purpose: copy them from the
generated block in [`JUDGE_QA.md`](JUDGE_QA.md) or from [`results/REPORT.md`](../results/REPORT.md), so a slide can never disagree with the results.
Rule for every slide: **say which split a number comes from** (DEV, holdout, or fresh), and never merge the five numbers into one score.

| # | Message | On the slide | Asset | Say |
|---|---|---|---|---|
| 1 | Is this the sensor, or is this the sky? | Title, one line, the Delhi screenshot | `docs/screenshots/03_live_monitor_injected_fault_delhi.png` | A barometer that has stuck and a cyclone look the same on a chart. We tell them apart from one station's own T, P and RH. |
| 2 | The problem is real and unforgiving | Two failure modes: delete the storm, or trust the fault | `docs/figures/diagram_sensor_or_sky.png` | Filters that clean everything delete what the network exists to see. Sparse networks have no neighbours to ask. |
| 3 | Standard rules fail on real weather | Textbook range + step + persistence: its false alarms and how many real extreme-weather windows it calls a FAULT | `results/REPORT.md` (trade-off table), `docs/figures/fig_baselines.png` | Same real data, same five numbers, for us and for simpler systems. |
| 4 | Four verdicts, and weather is one of them | The pipeline, the four verdicts, what comes with each | `docs/figures/diagram_pipeline.png` | WEATHER is escalated as an alert and never deleted. The raw value is never overwritten. |
| 5 | Limits belong to the station | Learned frozen run, jitter, usual step; the two-tier frozen rule | `docs/TECHNICAL_REPORT.md` section 3.3 | Fixed limits alarmed on most clean real data; learned ones do not. That was the first thing real data taught us. |
| 6 | The evidence was produced in an order you can check | Protocol first, holdout once, amendments, fresh run | `docs/figures/diagram_evidence.png`, `config/protocol.md` | Every step is a commit; a lock file records each single run. |
| 7 | Results, split by split | The three or four-column headline table | README results block | DEV is the optimistic column; the others are the ones to trust. |
| 8 | What each layer is worth, and where simpler systems win | Ablation and baselines; the honest note that a Mahalanobis-only detector beats us on spikes and is blind to frozen sensors and dropouts | `docs/figures/fig_ablation.png`, trade-off table | We do not claim the Isolation Forest matters: the ablation says it does not, and it is most of the run time. |
| 9 | Real cyclones, nothing injected | Vardah, Fani, Amphan with the verdict on every reading | `docs/figures/fig_real_cyclones.png` | The pressure crash is escalated, never called a fault. |
| 10 | Where it failed, and what we did about it | The three holdout windows with a FAULT; the two remedies; the pre-registered rule; the fresh-station result | `docs/HOLDOUT_POSTMORTEM.md`, `docs/figures/fig_remedies.png` | We did not tune on the holdout. We set the rule first, then tested the remedies on twelve stations nobody had looked at. |
| 11 | A new station works on day one | Cold-start curves | `docs/figures/fig_coldstart.png` | A frozen starter from the nearest other station, blended out as history grows; no live data of another station. |
| 12 | Fast enough, honest about what is fast | Speed and scale, with and without the Isolation Forest | `docs/figures/fig_scale.png`, speed lines in the numbers block | Per-station state, so cost per reading does not grow with stations. |
| 13 | On the device and in the room | ESP32 node, the edge-parity test, the live break-the-sensor demo | `docs/HARDWARE.md`, `docs/demo/dashboard_walkthrough.webm` | The device's first layer is one header, compiled and compared with the Python. It has not run on hardware yet, and we say so. |
| 14 | What we do not claim | The list | `docs/WHAT_WE_DO_NOT_CLAIM.md` | Injected faults are injected. Airport records are not IMD AWS records. Small drift and constant offsets are invisible from one station. |
| 15 | Who it helps, and what is next | Cyclone warnings, NWP and advisories, aviation pressure safety, maintenance, sparse networks; real AWS data via `evaluate_csv.py`; tau_RH research | `docs/USE_CASES.md`, `docs/USE_YOUR_DATA.md` | One command turns any real AWS record into the same tables. |

## Ten-minute path through the room demo
1. `docs/demo/index.html` or the dashboard: replay Vardah. Point at the purple triangles (WEATHER).
2. Control panel: arm a frozen barometer on Delhi, replay the outflow. Point at the red crosses (FAULT) and the health score falling.
3. Evaluation tab: the headline table. Say which split each column is.
4. Hand over `docs/JUDGE_QA.md`'s three certain questions: how is this different from WMO checks, what is the false-alarm rate on real cyclones, why should we believe the holdout.
