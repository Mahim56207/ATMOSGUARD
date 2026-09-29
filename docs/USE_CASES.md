# Use cases

AtmosGuard is a quality-control layer that sits between an Automatic Weather Station and whatever consumes its data. It
answers one question per reading: *is this the sensor, or is this the sky?*

## 1. Cyclone and severe-weather warnings (IMD)
A tropical cyclone shows up as a pressure crash - and so does a failing barometer. A filter that deletes "impossible"
pressure drops removes the most important observation of the year. AtmosGuard escalates a coherent multi-channel change
(`WEATHER`) as an alert and keeps the reading. On real records (Fani at Bhubaneswar, Vardah and Michaung at Chennai, Amphan
and Remal at Kolkata, Tauktae at Mumbai and Ahmedabad, Biparjoy at Bhuj) the number that matters is the rate of `FAULT`
verdicts on real extreme weather; it is reported separately in `results/REPORT.md`.

## 2. Numerical weather prediction and agriculture advisories
A poisoned reading that gets into assimilation corrupts a forecast; a dropped real extreme misses a heat-wave or cold-wave
advisory. The verdict lets a downstream system take `VALID` and `WEATHER`, hold `SUSPECT` for review, and drop `FAULT`, with
raw data never deleted (the raw value, the verdict and any estimate are stored side by side).

## 3. Aviation pressure safety
Pressure is a safety input for altimetry. A frozen or drifting pressure channel is a `FAULT` or a health-score problem
before it becomes a misleading QNH. The L0 checks run on the station itself, so an impossible value never leaves it.

## 4. Maintenance planning
The health monitor turns fault history and drift into a per-channel score, a ticket (high or normal priority, the channels
involved, the reason) and, when a drift is significant, a projected service date. It also reports the *smallest drift it
can see* at that station, so a technician knows what "no drift found" does and does not mean.

## 5. Sparse and remote networks (Ladakh, the Thar, the Andamans)
Most operational QC compares a station with its neighbours or with a forecast model. That fails where the nearest station is
hundreds of kilometres away. Every AtmosGuard check uses one station and its own history, and a new station starts from a frozen
table of its nearest other station on day one, then leans on its own history as it grows (the cold-start table in `results/REPORT.md`).

## Who acts on what
| Output | Consumer | Action |
|---|---|---|
| `WEATHER` alert | forecaster / warning centre | look at it now; it is probably real |
| `FAULT` | data pipeline | do not assimilate; open a ticket |
| `SUSPECT` | QC analyst | review; the reading is kept |
| ticket + service date | field technician | plan the visit |
| notice (gap) | network operations | the link was down; the values after it are fine |
