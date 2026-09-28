# Failure-mode catalogue

For each fault type: what it is, what catches it, what the verdict looks like, and what we know about how well it works.
Numbers are from `results/REPORT.md` (real data, injected faults). The last section lists what the system **cannot** see.

## Faults the system detects

| Fault | What it looks like | Detected by | Verdict | Notes |
|---|---|---|---|---|
| Impossible value | RH 140 %, T -120 °C, dew point above air temperature | L0 physics (also on the ESP32) | FAULT | closed-form, no training |
| Missing value / dropout | a channel is null, a packet is empty | L1 dropout check | FAULT | value is imputed with a band; raw is kept as null |
| Frozen sensor | the same value for many samples | L1 frozen check with a **station-learned** window | SUSPECT just past the learned limit, FAULT at twice the limit | learned from clean history so rounded stations are not called stuck; limit is a longer window at coarse resolution, so a stuck sensor is caught after about a day at hourly cadence, not after an hour |
| Spike | one sample jumps out and back | L1 spike check | FAULT if one channel jumps while the other two stay calm | |
| Level shift | a constant offset from a moment on | L1 step (at the edge), L2 normality (afterwards) | FAULT at the edge, SUSPECT while it persists | |
| Noise burst | jitter far above the station's normal | L1 noise check with a station-learned ceiling | SUSPECT / FAULT | the learned ceiling is high for whole-degree data; small noise bursts hide inside rounding |
| Common-mode glitch | all channels jump in the same sample | T2 co-jump | SUSPECT | meaningful only at fast cadence (minutes); on hourly data it is weak, and the README says so |
| Clock / timestamp shift | values carry the wrong hour | T1 diurnal-phase check | SUSPECT | needs a day of history; recomputed every 3 hours of data |
| Communication gap | readings stop, then resume | L1 gap check | **notice** on the next reading, not a verdict | a healthy reading after a gap is not called suspect |
| Multichannel oddity | a mix of values unusual for this station | L3 Isolation Forest | SUSPECT | weak on a gross error in one channel: the other layers catch those |
| Slow drift | a channel walks away over weeks | health monitor: daily means, Theil-Sen, autocorrelation-aware test, isolated-trend rule, persistence | health score falls, ticket, service date | see limits below |

## Real weather the system must not call a fault

| Situation | What happens | Why |
|---|---|---|
| Cyclone: pressure falls tens of hPa, humidity rises, temperature drops | `WEATHER` when several channels move together in a known pattern, else `SUSPECT`; **not FAULT** | fusion rule 3; a pressure plateau inside the low is graded, not hard-flagged |
| Heat wave: extreme temperature for days | normality flags → `SUSPECT`/`WEATHER`, not FAULT | normality and drift flags are soft |
| Cold wave, dense fog | same | same |
| Thunderstorm outflow / nor'wester: several channels change within hours | `WEATHER` or `SUSPECT` | step limits allow fast weather; a co-jump needs the change to be simultaneous in one sample |
| Monsoon onset: humidity trends up for weeks | *not* reported as sensor drift | isolated-trend rule: several channels are trending together |

## What the system cannot see (say this out loud)

1. **A constant offset present from the start.** No single-station method can see it.
2. **Drift slower than the detectability floor.** The dashboard shows the smallest slope it can see at this station now.
   On our real data that is several times the service limit within weeks.
3. **A drift that starts during a weather or seasonal transition.** The isolated-trend rule masks it until the transition ends.
4. **A stuck sensor that sits at a value the station commonly holds** for less than the learned frozen limit (about half a day
   to a day at hourly cadence, longer for humidity).
5. **Small noise increases.** At whole-degree resolution they are inside the rounding.
6. **Faults hidden inside data gaps.** The gap is reported; what happened inside it is not known.
7. **A weather event that looks exactly like a fault** (a real one-channel jump). Rule 2 would call it a fault. We tune toward
   protecting weather (mixed evidence is `SUSPECT`, not `FAULT`), and we report the FAULT rate on real extreme weather
   separately so the cost is visible.
8. **Anything that needs a reference:** neighbour stations, a forecast model, a calibration record. By design we use none.
