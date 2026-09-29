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

## What happened next: the remedies, tested on stations nobody had looked at
The two remedies above were not applied to the sealed holdout. Instead we registered a decision rule (Amendment 2 in `config/protocol.md`) and tested both on
twelve more Indian stations that had not been used for anything (`data_tools/stations_fresh.yaml`), in one run behind its own guard. The result, judged by
that rule and nothing else:

- **Remedy 1, the ceiling-aware frozen rule, is adopted.** Real extreme-weather windows with a `FAULT`: 3 of 139 become 2; detection and false alarms are
  unchanged. The window it removed is Ranchi in May 2021: humidity at 100 % for more than 35 hours, the same cause as Visakhapatnam.
- **Remedy 2, the station-learned step cap, is rejected.** It also takes the windows from 3 to 2 and lowers clean false alarms slightly, but it costs 4.2 points of
  wrong-clock detection: the same fixed step cap is what flags the jump when a logger clock goes wrong. That breaks rule (b), so it is not shipped.
- The frozen pipeline on these twelve stations had 3 windows with a `FAULT` out of 139 (0.1 % of samples): Ranchi (saturation), Coimbatore (humidity up 47 %
  in two hours against a 40 % cap, one sample) and Jodhpur (temperature up 16 C across a 6-hour reporting gap, the Bhuj cause again). So the two step causes are
  still open. A step cap that scales with the reporting gap, or that applies to the "one channel jumped" rule only, is the obvious next candidate, and it would
  need a third set of unseen stations to be judged honestly.

What the adopted remedy costs: a humidity sensor that really is stuck at 100 % is now a `SUSPECT` (review), not a `FAULT`, until it disagrees with the other
channels or the health score drops. We take that trade because sustained saturation is real weather more often than a stuck sensor is, and we say so.


## What happened after that: the third set (Amendment 3)
The step causes were the open item. A step cap that scales with what the station's own daily cycle explains was registered as remedy 3 (with a second remedy aimed at level shifts) and tested once on twelve more
stations nobody had looked at: five Indian airports and seven Australian automatic weather stations (`data_tools/stations_fresh2.yaml`). By the rule registered first, **remedy 3 is adopted**: real
extreme-weather windows with a `FAULT` 4 to 1 of 134 (the four were fast humidity drops and an afternoon warming at Giles in the desert and Thredbo in the Alps), no detection type moved, clean false alarms
-0.02 points. The one window left is Thredbo, October 2023 (humidity -48.9 % in two hours). Remedy 4 (a sustained one-channel offset) is **rejected**: level-shift detection +1 point against the +5 registered,
clean false alarms +0.48 points. Details and every number: Amendment 3 and its outcome in `config/protocol.md`, `results/REPORT.md`.
