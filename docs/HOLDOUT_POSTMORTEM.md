# What the holdout found

The holdout exists to find what DEV could not. On the eight stations never used for any tuning, **3 of 98 real extreme-weather windows contain a
`FAULT` verdict** (0.3 % of those samples). On the same six DEV stations in later years, none of 38 do, and DEV had none of 30. This is a
post-mortem: it explains the three windows and proposes remedies. **The pipeline was not changed in response**, because that would be tuning on the
holdout; the numbers in `results/REPORT.md` are for the pipeline exactly as frozen in commit `9cd24f1`. (The windows were read only to explain
verdicts already reported.)

## The three windows
| Station | Event | What the data did | Which rule fired | Why it is wrong |
|---|---|---|---|---|
| Visakhapatnam | low-pressure window centred 26 Sep 2021 | humidity at exactly 100 % for 22+ hours | `frozen:humidity_pct` beyond twice the learned limit -> hard -> FAULT | Sustained torrential rain gives T = Td, so derived RH is pinned at its physical ceiling. A saturated stuck sensor and a real downpour look identical without rain information. |
| Visakhapatnam | low-pressure window centred 8 Sep 2024 | humidity pinned at 100 % and temperature at 26 C for about 38 hours, while pressure kept moving (998-1001 hPa) | `frozen:humidity_pct` and `frozen:temperature_c` | Same cause: an isothermal, saturated air mass has no diurnal cycle either. |
| Bhuj (3-hourly SYNOP, arid) | sharp-temperature-change window centred 16 Feb 2023 (the verdict is on 14 Feb) | one 6-hour gap in the reports, then temperature +15.6 C over the gap (18.6 -> 34.2) with pressure and humidity changing ordinarily | `step:temperature_c` (allowed 10 C) -> rule 2 -> FAULT | An arid station warms 15 C between about 08:30 and 14:30 local time on a clear day; the fixed 10 C step cap is wrong for a 3-hourly (here 6-hourly) interval at a desert station. |

## Proposed remedies (not applied, not evaluated)
1. **Ceiling-aware frozen rule.** A channel pinned at a physical limit (humidity at 100 %) is at most a **soft** flag, and temperature frozen while humidity is
   saturated is soft too. Reason: saturation is a ceiling that real weather holds for a day or more. A stuck sensor at 100 % would then be `SUSPECT`, not `FAULT`;
   it would be caught by the health score and by a disagreement with the other channels, which is weaker but honest.
2. **Station-learned step cap.** Replace the fixed 10 C / 10 hPa / 40 % caps by the 99.9th percentile of |change| at the station's cadence from its clean history
   (the same treatment the frozen and noise limits already get), never below the configured value. Reason: the largest ordinary change depends on cadence and climate.

Both are small, both follow the pattern the real data taught us (limits belong to the station and the cadence), and both need a fresh set of unseen stations to be
evaluated honestly. Re-running them on this holdout would turn it into a tuning set, so they are listed as next work.

## What it says about the claim
The claim is "0 FAULT on real extreme weather" on DEV and on the time holdout, and "0.3 % of samples, 3 of 98 windows" on unseen stations, with the cause of each. It is
not "never". The textbook rules baseline gets 95 of those 98 windows wrong.
