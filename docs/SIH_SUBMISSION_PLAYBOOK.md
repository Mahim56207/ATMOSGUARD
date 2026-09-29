# SIH submission playbook

What the research found about how entries are judged, what we have that others do not, what is left for the team, and
where each judging criterion is answered in this repository. (The final slide deck is deliberately not part of this
repository yet.)

## What the sources say
- **Official criteria** (SIH guidelines as summarised by several college pages): novelty of the idea, complexity, clarity and
  detail in the prescribed format, feasibility, practicability, sustainability, scale of impact, user experience, and
  potential for future progression. Teams are asked to validate a prototype wherever possible.
- **Problem-statement weights** (from the team's own guide for PS 26073): innovation and novelty 25 %, detection accuracy 20 %,
  real-time 15 %, explainability 10 %, scalability 10 %, deployability 10 %, visualisation 5 %, energy 5 %.
- **Grand finale format:** a 36-hour build-and-present event at a nodal centre in front of expert judges. SIH 2025 finalists
  worked on state-government problems; the 2024 and 2025 winner write-ups describe **working full-stack prototypes,
  real-time demos, and hardware prototypes built with Arduino/IoT sensors** as what impressed judges, including teams that
  demonstrated despite connectivity problems.
- **The field on this problem statement is crowded.** At least fourteen public repositories target it (survey in
  `docs/NOVELTY_AND_PRIOR_ART.md`). Read from their READMEs, almost all are synthetic-only or have no metrics; none shows a
  locked holdout, a real-cyclone false-alarm figure, an ablation on real data, or a list of what it cannot do. Judges who see
  several entries side by side will remember the one with evidence and honesty.

## Our position, in one paragraph
Not "a new algorithm" (we say plainly it is not) but the strongest **evidence**: 26 real Indian stations, a holdout sealed in
time and in space with the protocol committed first, false alarms on real cyclones reported separately, baselines and an
ablation on the same data, agreement with NOAA's quality flags, the failures real data exposed and how they were fixed, a
detectability floor stated for drift, edge code that is compiled and tested against the Python, and a live
break-the-sensor-on-demand control. That maps to the criteria as follows.

## Criterion -> where it is answered
| Criterion | Where |
|---|---|
| Novelty (25 %) | `docs/NOVELTY_AND_PRIOR_ART.md`: standard vs adapted vs ours, prior art per claim, the exact submission sentence. Lead with evidence and integration; put tau_RH on the roadmap as measured research (`research/tau_rh.py`) |
| Detection accuracy (20 %) | `results/REPORT.md` tables 1 and 2: injected faults by type, clean false alarms, DEV and both HOLDOUTs, with baselines and ablation |
| Real-time (15 %) | `loadtest.py` / `results/scale.json`: median and 95th-percentile time per reading, in-process and through the real HTTP server |
| Explainability (10 %) | every verdict has a plain-English reason and the checks behind it (dashboard, Live monitor); confidence is defined honestly (agreement, not probability) |
| Scalability (10 %) | `loadtest.py`: 1 to 200 simulated stations, latency vs station count, memory and storage per station; per-station state, no shared computation |
| Deployability (10 %) | Docker Compose, committed models and data so a fresh clone runs, `/docs` OpenAPI, CI; ESP32 node with the same limits generated from one config |
| Visualisation (5 %) | Streamlit: live monitor, control panel, evaluation tab, how it decides |
| Energy (5 %) | `docs/HARDWARE.md`: honest estimate and the measurement recipe. **Not measured yet; do this with a USB power meter** |
| Feasibility / practicability | `docs/USE_CASES.md`; runs on a laptop; ESP32 + BME280 about Rs 700-1,500 |
| Potential for future work | `docs/WHAT_WE_DO_NOT_CLAIM.md` (the honest boundary), cold-start for new stations, tau_RH paired-sensor roadmap |

## What is left for the team (things only you can do)
1. **Run `docker compose up --build` once on your own machine** (Docker was not available where this was built). If it does not
   come up in one command, fix it or drop the claim.
2. **Flash the ESP32** (`docs/HARDWARE.md`), let it run for an hour, press the fault controls from the dashboard. If anything
   fails, `simnode.py` gives the same readings.
3. **Measure the current** in three states with a USB power meter (the energy table).
4. **Record the backup demo video** from `docs/DEMO_RUNBOOK.md` with the venue's network off, and keep it on the laptop.
5. **Rehearse with the Q&A** in `docs/JUDGE_QA.md`, out loud, with a stopwatch.
6. **Optional but the strongest addition: real IMD or AWS data.** If any faculty or contact can share a real AWS record (about two
   years are needed so every month has data), run `python evaluate_csv.py their.csv --station NAME` and read
   [`USE_YOUR_DATA.md`](USE_YOUR_DATA.md). It gives the same tables for that station. Even a shorter record is worth trying with `--quick`;
   the script says how weak the result will be.
7. **The PPT** - after you have read the results and decided what to lead with.

## The three claims to lead with, and the three not to make
Lead with: (1) the false-alarm rate on **real** cyclones and heat waves, reported separately from injected faults;
(2) the holdout was sealed in time and in space and run once; (3) here is what we cannot do, with numbers.

Do not claim: that any technique is new; that injected-fault accuracy is real-world accuracy; that tau_RH works in the field.
