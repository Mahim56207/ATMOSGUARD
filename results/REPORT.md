# AtmosGuard evaluation results

Real NOAA ISD airport records (METAR and SYNOP), 2016-2024. RH is derived from dew point. Injected faults are injected. NOAA agreement is not ground truth. See docs/WHAT_WE_DO_NOT_CLAIM.md.

## DEV: the six stations we were allowed to tune on, 2020-2021

*Tuning happened here. These numbers are the optimistic ones.*  Stations: BBI, MAA, CCU, DEL, JAI, TRV.

### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 1.9% (1.8-2.0) of 98340 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.0% (0.0-0.1) of 3503 samples (0 of 30 windows); WEATHER on 10.8%, SUSPECT on 9.0% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 98%; level shift 97%; noise burst 78%; dropout 99%; clock 3 h out 97% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 66.9% of 236 NOAA-flagged values (FAULT or SUSPECT alone: 22.9%); escalated on 4.7% of the 101736 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 1.1% of 3859 station-days; an injected ramp reaching 8x the service limit was found in 56% of trials |

### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 98% | 97% | 78% | 99% | 97% |
| without physics layer | 100% | 97% | 96% | 76% | 99% | 97% |
| without health layer | 37% | 88% | 92% | 60% | 1% | 94% |
| without normality layer | 100% | 99% | 95% | 79% | 100% | 94% |
| without Isolation Forest | 100% | 98% | 97% | 77% | 99% | 97% |
| without Mahalanobis layer | 100% | 91% | 70% | 61% | 99% | 97% |
| without timing layer | 100% | 98% | 97% | 78% | 100% | 70% |
| without station-learned limits | 100% | 46% | 89% | 98% | 60% | 100% |
| baseline: range check only | 0% | 12% | 12% | 16% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 74% | 87% | 67% | 0% | 89% |
| baseline: climatology z-score only | 18% | 37% | 33% | 13% | 0% | 58% |
| baseline: Isolation Forest only | 1% | 12% | 10% | 10% | 0% | 56% |
| baseline: Mahalanobis distance only | 38% | 100% | 100% | 74% | 0% | 55% |
| (faults injected) | 243 | 243 | 243 | 243 | 243 | 220 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 420 | 0 | 1140 |

### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 243 | 100.0% (98.4-100.0) | 95.1% (91.6-97.2) |
| spike | 243 | 97.5% (94.7-98.9) | 12.3% (8.8-17.1) |
| level shift | 243 | 97.1% (94.2-98.6) | 11.5% (8.1-16.1) |
| noise burst | 243 | 77.8% (72.1-82.5) | 15.6% (11.6-20.7) |
| dropout | 243 | 99.2% (97.0-99.8) | 99.2% (97.0-99.8) |
| clock 3 h out | 220 | 96.8% (93.6-98.5) | 0.5% (0.1-2.5) |

### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 98% | 97% | 78% | 99% | 97% |
| of which named FAULT | 95% | 12% | 12% | 16% | 99% | 0% |
| missed, but made some samples look like WEATHER | 0% | 1% | 3% | 5% | 0% | 2% |

### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 99% | 97% | 81% | 100% | 97% |
| without physics layer | 100% | 98% | 96% | 79% | 100% | 97% |
| without health layer | 40% | 88% | 92% | 62% | 3% | 94% |
| without normality layer | 100% | 99% | 95% | 81% | 100% | 94% |
| without Isolation Forest | 100% | 99% | 97% | 80% | 100% | 97% |
| without Mahalanobis layer | 100% | 93% | 74% | 65% | 100% | 97% |
| without timing layer | 100% | 99% | 97% | 81% | 100% | 70% |
| without station-learned limits | 100% | 100% | 100% | 100% | 100% | 100% |
| baseline: range check only | 0% | 12% | 12% | 16% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 78% | 92% | 82% | 8% | 90% |
| baseline: climatology z-score only | 24% | 38% | 36% | 17% | 2% | 59% |
| baseline: Isolation Forest only | 4% | 12% | 15% | 19% | 0% | 56% |
| baseline: Mahalanobis distance only | 46% | 100% | 100% | 77% | 0% | 55% |
| (faults injected) | 243 | 243 | 243 | 243 | 243 | 220 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 360 | 0 | 1140 |

### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 78% | 1.9% | 0/30 |
| baseline: range check only | frozen: 0% | 0.0% | 0/30 |
| baseline: textbook range + step + persistence | dropout: 0% | 5.4% | 29/30 |
| baseline: climatology z-score only | dropout: 0% | 0.8% | 0/30 |
| baseline: Isolation Forest only | dropout: 0% | 0.4% | 0/30 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.5% | 0/30 |

### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 1.9% | 0.0% | 2.2% | 98340 |
| without physics layer | 1.9% | 0.0% | 2.2% | 98340 |
| without health layer | 0.6% | 0.0% | 1.3% | 98340 |
| without normality layer | 1.0% | 0.0% | 0.8% | 98340 |
| without Isolation Forest | 1.9% | 0.0% | 1.9% | 98340 |
| without Mahalanobis layer | 1.8% | 0.0% | 1.9% | 98340 |
| without timing layer | 1.7% | 0.0% | 2.1% | 98340 |
| without station-learned limits | 63.1% | 34.2% | 0.5% | 98340 |
| baseline: range check only | 0.0% | 0.0% | - | 98340 |
| baseline: textbook range + step + persistence | 5.4% | 5.4% | - | 98340 |
| baseline: climatology z-score only | 0.8% | 0.0% | - | 98340 |
| baseline: Isolation Forest only | 0.4% | 0.0% | - | 98340 |
| baseline: Mahalanobis distance only | 0.5% | 0.0% | - | 98340 |

### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.0% | 9.0% | 10.8% | 80.3% | 0/30 |
| without physics layer | 0.0% | 9.0% | 10.8% | 80.3% | 0/30 |
| without health layer | 0.0% | 3.9% | 7.1% | 89.1% | 0/30 |
| without normality layer | 0.0% | 3.6% | 3.1% | 93.3% | 0/30 |
| without Isolation Forest | 0.0% | 9.0% | 9.9% | 81.1% | 0/30 |
| without Mahalanobis layer | 0.0% | 8.8% | 10.4% | 80.8% | 0/30 |
| without timing layer | 0.0% | 8.9% | 10.7% | 80.4% | 0/30 |
| without station-learned limits | 28.6% | 34.3% | 4.1% | 33.0% | 30/30 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/30 |
| baseline: textbook range + step + persistence | 5.3% | 0.0% | - | 94.7% | 29/30 |
| baseline: climatology z-score only | 0.0% | 8.1% | - | 91.9% | 0/30 |
| baseline: Isolation Forest only | 0.0% | 2.1% | - | 97.9% | 0/30 |
| baseline: Mahalanobis distance only | 0.0% | 1.9% | - | 98.1% | 0/30 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 290 | 0.0% | 4.1% | 2.8% | 0/2 |
| heat | 270 | 0.0% | 1.5% | 10.7% | 0/2 |
| low | 1826 | 0.0% | 13.3% | 15.0% | 0/14 |
| sharp | 1117 | 0.0% | 4.9% | 5.9% | 0/12 |

### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 236 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 22.9% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 66.9% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 101736 |
| AtmosGuard alarmed on those (extra flags) | 2.3% |
| AtmosGuard escalated at all on those | 4.7% |

### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 15.8% of 19 chunks | 0.0% of 19 chunks | 21.1% of 19 chunks |
| 1x service limit | 5% of 19 (day 67, 3.6x at detection) | 0% of 19 (-, - at detection) | 11% of 19 (day 87, 2.6x at detection) |
| 2x service limit | 5% of 19 (day 62, 4.5x at detection) | 0% of 19 (-, - at detection) | 16% of 19 (day 45, 3.1x at detection) |
| 4x service limit | 16% of 19 (day 46, 4.4x at detection) | 16% of 19 (day 39, 4.0x at detection) | 32% of 19 (day 44, 4.6x at detection) |
| 8x service limit | 58% of 19 (day 41, 7.0x at detection) | 47% of 19 (day 45, 5.5x at detection) | 63% of 19 (day 46, 6.8x at detection) |

### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| BBI | 60 | 1.8% | 0.0% | 0.0% | 0/7 | 10.5% | 94% |
| MAA | 60 | 2.5% | 0.0% | 0.0% | 0/6 | 16.1% | 99% |
| CCU | 60 | 1.9% | 0.0% | 0.0% | 0/5 | 13.8% | 92% |
| DEL | 60 | 1.6% | 0.0% | 0.0% | 0/4 | 11.5% | 94% |
| JAI | 60 | 1.9% | 0.0% | 0.0% | 0/6 | 3.4% | 91% |
| TRV | 60 | 1.6% | 0.0% | 0.0% | 0/2 | 8.9% | 99% |

## HOLDOUT in time: the same six stations, 2022-2024

*Sealed until the single holdout run. Same stations, later years.*  Stations: BBI, MAA, CCU, DEL, JAI, TRV.

### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 2.5% (2.4-2.6) of 147078 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.0% (0.0-0.1) of 4374 samples (0 of 38 windows); WEATHER on 11.8%, SUSPECT on 8.2% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 96%; level shift 98%; noise burst 79%; dropout 100%; clock 3 h out 97% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 61.5% of 265 NOAA-flagged values (FAULT or SUSPECT alone: 18.5%); escalated on 5.7% of the 151336 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 1.1% of 5797 station-days; an injected ramp reaching 8x the service limit was found in 50% of trials |

### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 96% | 98% | 79% | 100% | 97% |
| without physics layer | 100% | 95% | 96% | 77% | 100% | 97% |
| without health layer | 44% | 87% | 96% | 62% | 2% | 90% |
| without normality layer | 100% | 98% | 97% | 80% | 100% | 94% |
| without Isolation Forest | 100% | 96% | 98% | 79% | 100% | 97% |
| without Mahalanobis layer | 100% | 92% | 75% | 66% | 100% | 97% |
| without timing layer | 100% | 97% | 98% | 80% | 100% | 71% |
| without station-learned limits | 100% | 51% | 91% | 97% | 61% | 100% |
| baseline: range check only | 0% | 14% | 15% | 13% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 75% | 87% | 68% | 0% | 91% |
| baseline: climatology z-score only | 22% | 43% | 47% | 13% | 0% | 53% |
| baseline: Isolation Forest only | 1% | 10% | 13% | 13% | 0% | 46% |
| baseline: Mahalanobis distance only | 37% | 100% | 100% | 76% | 0% | 47% |
| (faults injected) | 279 | 279 | 279 | 279 | 279 | 260 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 420 | 0 | 1050 |

### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 279 | 100.0% (98.6-100.0) | 95.0% (91.8-97.0) |
| spike | 279 | 96.4% (93.5-98.0) | 14.7% (11.0-19.3) |
| level shift | 279 | 98.2% (95.9-99.2) | 14.7% (11.0-19.3) |
| noise burst | 279 | 79.2% (74.1-83.6) | 12.5% (9.2-16.9) |
| dropout | 279 | 99.6% (98.0-99.9) | 99.6% (98.0-99.9) |
| clock 3 h out | 260 | 96.9% (94.0-98.4) | 0.0% (0.0-1.5) |

### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 96% | 98% | 79% | 100% | 97% |
| of which named FAULT | 95% | 15% | 15% | 13% | 100% | 0% |
| missed, but made some samples look like WEATHER | 0% | 1% | 2% | 6% | 0% | 2% |

### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 99% | 99% | 82% | 100% | 97% |
| without physics layer | 100% | 98% | 97% | 80% | 100% | 97% |
| without health layer | 50% | 88% | 96% | 64% | 2% | 90% |
| without normality layer | 100% | 99% | 98% | 82% | 100% | 95% |
| without Isolation Forest | 100% | 99% | 99% | 82% | 100% | 97% |
| without Mahalanobis layer | 100% | 95% | 76% | 68% | 100% | 97% |
| without timing layer | 100% | 99% | 99% | 82% | 100% | 72% |
| without station-learned limits | 100% | 100% | 100% | 100% | 100% | 100% |
| baseline: range check only | 0% | 14% | 15% | 13% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 78% | 94% | 82% | 10% | 92% |
| baseline: climatology z-score only | 27% | 44% | 48% | 18% | 3% | 53% |
| baseline: Isolation Forest only | 4% | 10% | 18% | 18% | 0% | 47% |
| baseline: Mahalanobis distance only | 46% | 100% | 100% | 81% | 0% | 47% |
| (faults injected) | 279 | 279 | 279 | 279 | 279 | 260 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 360 | 0 | 1020 |

### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 79% | 2.5% | 0/38 |
| baseline: range check only | frozen: 0% | 0.0% | 0/38 |
| baseline: textbook range + step + persistence | dropout: 0% | 5.2% | 37/38 |
| baseline: climatology z-score only | dropout: 0% | 0.9% | 0/38 |
| baseline: Isolation Forest only | dropout: 0% | 0.4% | 0/38 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.5% | 0/38 |

### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 2.5% | 0.0% | 2.7% | 147078 |
| without physics layer | 2.5% | 0.0% | 2.7% | 147078 |
| without health layer | 0.7% | 0.0% | 1.5% | 147078 |
| without normality layer | 1.2% | 0.0% | 0.8% | 147078 |
| without Isolation Forest | 2.5% | 0.0% | 2.4% | 147078 |
| without Mahalanobis layer | 2.4% | 0.0% | 2.4% | 147078 |
| without timing layer | 2.2% | 0.0% | 2.6% | 147078 |
| without station-learned limits | 61.2% | 34.1% | 0.8% | 147078 |
| baseline: range check only | 0.0% | 0.0% | - | 147078 |
| baseline: textbook range + step + persistence | 5.2% | 5.2% | - | 147078 |
| baseline: climatology z-score only | 0.9% | 0.0% | - | 147078 |
| baseline: Isolation Forest only | 0.4% | 0.0% | - | 147078 |
| baseline: Mahalanobis distance only | 0.5% | 0.0% | - | 147078 |

### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.0% | 8.2% | 11.8% | 80.0% | 0/38 |
| without physics layer | 0.0% | 8.2% | 11.8% | 80.0% | 0/38 |
| without health layer | 0.0% | 2.5% | 7.0% | 90.5% | 0/38 |
| without normality layer | 0.0% | 4.4% | 2.9% | 92.7% | 0/38 |
| without Isolation Forest | 0.0% | 8.2% | 11.1% | 80.7% | 0/38 |
| without Mahalanobis layer | 0.0% | 8.0% | 10.7% | 81.3% | 0/38 |
| without timing layer | 0.0% | 8.1% | 11.8% | 80.1% | 0/38 |
| without station-learned limits | 33.7% | 31.1% | 3.7% | 31.6% | 38/38 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/38 |
| baseline: textbook range + step + persistence | 7.1% | 0.0% | - | 92.9% | 37/38 |
| baseline: climatology z-score only | 0.0% | 5.7% | - | 94.3% | 0/38 |
| baseline: Isolation Forest only | 0.0% | 1.7% | - | 98.3% | 0/38 |
| baseline: Mahalanobis distance only | 0.0% | 2.0% | - | 98.0% | 0/38 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 425 | 0.0% | 0.7% | 4.9% | 0/3 |
| heat | 653 | 0.0% | 8.1% | 19.9% | 0/5 |
| low | 1622 | 0.0% | 15.8% | 19.2% | 0/12 |
| sharp | 1674 | 0.0% | 2.8% | 3.2% | 0/18 |

### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 265 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 18.5% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 61.5% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 151336 |
| AtmosGuard alarmed on those (extra flags) | 2.8% |
| AtmosGuard escalated at all on those | 5.7% |

### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 19.2% of 26 chunks | 7.7% of 26 chunks | 15.4% of 26 chunks |
| 1x service limit | 4% of 26 (day 49, 1.7x at detection) | 4% of 26 (day 264, 3.6x at detection) | 12% of 26 (day 281, 2.5x at detection) |
| 2x service limit | 8% of 26 (day 51, 3.2x at detection) | 0% of 26 (-, - at detection) | 12% of 26 (day 281, 3.9x at detection) |
| 4x service limit | 19% of 26 (day 49, 4.7x at detection) | 19% of 26 (day 53, 4.0x at detection) | 23% of 26 (day 55, 5.1x at detection) |
| 8x service limit | 50% of 26 (day 49, 8.0x at detection) | 54% of 26 (day 55, 6.3x at detection) | 46% of 26 (day 36, 7.1x at detection) |

### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| BBI | 60 | 2.4% | 0.0% | 0.0% | 0/5 | 4.4% | 94% |
| MAA | 60 | 3.2% | 0.0% | 0.0% | 0/6 | 23.8% | 97% |
| CCU | 60 | 1.9% | 0.0% | 0.0% | 0/9 | 13.6% | 94% |
| DEL | 60 | 2.2% | 0.0% | 0.0% | 0/7 | 7.7% | 96% |
| JAI | 60 | 3.1% | 0.0% | 0.0% | 0/8 | 10.5% | 89% |
| TRV | 60 | 2.1% | 0.0% | 0.0% | 0/3 | 7.0% | 99% |

## HOLDOUT in space: eight stations never used for any tuning, 2020-2024

*Five hourly airport stations and three 3-hourly SYNOP stations (Port Blair, Bhuj, Cochin).*  Stations: AMD, NAG, BOM, GAU, VTZ, IXZ, BHJ, COK.

### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 2.9% (2.8-3.0) of 237411 samples got FAULT or SUSPECT; 0.0% (0.0-0.1) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.3% (0.2-0.4) of 9074 samples (3 of 98 windows); WEATHER on 15.7%, SUSPECT on 8.6% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 90%; level shift 89%; noise burst 67%; dropout 98%; clock 3 h out 84% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 67.6% of 559 NOAA-flagged values (FAULT or SUSPECT alone: 40.8%); escalated on 6.9% of the 246257 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.6% of 12495 station-days; an injected ramp reaching 8x the service limit was found in 56% of trials |

### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 90% | 89% | 67% | 98% | 84% |
| without physics layer | 100% | 88% | 88% | 65% | 98% | 84% |
| without health layer | 45% | 77% | 83% | 52% | 0% | 70% |
| without normality layer | 100% | 93% | 82% | 67% | 99% | 78% |
| without Isolation Forest | 100% | 90% | 89% | 67% | 98% | 84% |
| without Mahalanobis layer | 100% | 81% | 75% | 56% | 98% | 82% |
| without timing layer | 100% | 90% | 89% | 67% | 98% | 70% |
| without station-learned limits | 82% | 37% | 68% | 69% | 46% | 77% |
| baseline: range check only | 0% | 12% | 13% | 11% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 74% | 80% | 66% | 0% | 91% |
| baseline: climatology z-score only | 25% | 51% | 50% | 11% | 0% | 60% |
| baseline: Isolation Forest only | 3% | 17% | 16% | 15% | 0% | 56% |
| baseline: Mahalanobis distance only | 40% | 98% | 88% | 63% | 0% | 49% |
| (faults injected) | 702 | 702 | 702 | 702 | 702 | 619 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 360 | 0 | 1020 |

### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 702 | 99.9% (99.2-100.0) | 95.9% (94.1-97.1) |
| spike | 702 | 89.7% (87.3-91.8) | 17.0% (14.4-19.9) |
| level shift | 702 | 89.0% (86.5-91.1) | 13.4% (11.1-16.1) |
| noise burst | 702 | 67.4% (63.8-70.7) | 11.3% (9.1-13.8) |
| dropout | 702 | 98.4% (97.2-99.1) | 98.4% (97.2-99.1) |
| clock 3 h out | 619 | 83.5% (80.4-86.2) | 0.5% (0.2-1.4) |

### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 90% | 89% | 67% | 98% | 84% |
| of which named FAULT | 96% | 17% | 13% | 11% | 98% | 0% |
| missed, but made some samples look like WEATHER | 0% | 8% | 8% | 7% | 0% | 8% |

### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 93% | 92% | 76% | 100% | 84% |
| without physics layer | 100% | 91% | 91% | 74% | 100% | 84% |
| without health layer | 47% | 77% | 84% | 55% | 1% | 70% |
| without normality layer | 100% | 94% | 84% | 73% | 100% | 78% |
| without Isolation Forest | 100% | 93% | 92% | 76% | 100% | 84% |
| without Mahalanobis layer | 100% | 85% | 79% | 65% | 100% | 83% |
| without timing layer | 100% | 93% | 92% | 76% | 100% | 71% |
| without station-learned limits | 100% | 98% | 100% | 100% | 100% | 100% |
| baseline: range check only | 0% | 12% | 13% | 11% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 79% | 92% | 84% | 16% | 92% |
| baseline: climatology z-score only | 29% | 52% | 53% | 16% | 1% | 61% |
| baseline: Isolation Forest only | 7% | 18% | 22% | 21% | 0% | 56% |
| baseline: Mahalanobis distance only | 46% | 98% | 88% | 67% | 0% | 49% |
| (faults injected) | 702 | 702 | 702 | 702 | 702 | 619 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 360 | 0 | 960 |

### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 67% | 2.9% | 3/98 |
| baseline: range check only | frozen: 0% | 0.0% | 0/98 |
| baseline: textbook range + step + persistence | dropout: 0% | 6.8% | 95/98 |
| baseline: climatology z-score only | dropout: 0% | 1.1% | 0/98 |
| baseline: Isolation Forest only | dropout: 0% | 0.6% | 0/98 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.7% | 0/98 |

### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 2.9% | 0.0% | 3.2% | 237411 |
| without physics layer | 2.9% | 0.0% | 3.2% | 237411 |
| without health layer | 0.6% | 0.0% | 1.9% | 237411 |
| without normality layer | 1.6% | 0.0% | 1.1% | 237411 |
| without Isolation Forest | 2.9% | 0.0% | 2.9% | 237411 |
| without Mahalanobis layer | 2.7% | 0.0% | 2.8% | 237411 |
| without timing layer | 2.8% | 0.0% | 3.2% | 237411 |
| without station-learned limits | 67.7% | 25.8% | 0.9% | 237411 |
| baseline: range check only | 0.0% | 0.0% | - | 237411 |
| baseline: textbook range + step + persistence | 6.8% | 6.8% | - | 237411 |
| baseline: climatology z-score only | 1.1% | 0.0% | - | 237411 |
| baseline: Isolation Forest only | 0.6% | 0.0% | - | 237411 |
| baseline: Mahalanobis distance only | 0.7% | 0.0% | - | 237411 |

### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.3% | 8.6% | 15.7% | 75.4% | 3/98 |
| without physics layer | 0.3% | 8.6% | 15.7% | 75.4% | 3/98 |
| without health layer | 0.0% | 3.0% | 9.6% | 87.4% | 0/98 |
| without normality layer | 0.3% | 5.9% | 4.4% | 89.5% | 3/98 |
| without Isolation Forest | 0.3% | 8.6% | 14.8% | 76.4% | 3/98 |
| without Mahalanobis layer | 0.3% | 8.1% | 14.7% | 76.9% | 3/98 |
| without timing layer | 0.3% | 8.6% | 15.7% | 75.5% | 3/98 |
| without station-learned limits | 23.9% | 43.7% | 5.1% | 27.3% | 70/98 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/98 |
| baseline: textbook range + step + persistence | 7.7% | 0.0% | - | 92.3% | 95/98 |
| baseline: climatology z-score only | 0.0% | 7.6% | - | 92.4% | 0/98 |
| baseline: Isolation Forest only | 0.0% | 2.8% | - | 97.2% | 0/98 |
| baseline: Mahalanobis distance only | 0.0% | 3.5% | - | 96.5% | 0/98 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 2033 | 0.0% | 7.9% | 8.7% | 0/20 |
| heat | 1069 | 0.0% | 5.6% | 19.4% | 0/11 |
| low | 3222 | 0.7% | 13.5% | 25.6% | 2/27 |
| sharp | 2750 | 0.0% | 4.5% | 7.9% | 1/40 |

### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 559 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 40.8% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 67.6% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 246257 |
| AtmosGuard alarmed on those (extra flags) | 3.2% |
| AtmosGuard escalated at all on those | 6.9% |

### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 6.8% of 59 chunks | 11.9% of 59 chunks | 6.8% of 59 chunks |
| 1x service limit | 7% of 59 (day 79, 4.7x at detection) | 0% of 59 (-, - at detection) | 2% of 59 (day 29, 4.5x at detection) |
| 2x service limit | 15% of 59 (day 46, 4.0x at detection) | 3% of 59 (day 61, 3.1x at detection) | 5% of 59 (day 42, 3.4x at detection) |
| 4x service limit | 31% of 59 (day 47, 6.3x at detection) | 12% of 59 (day 47, 4.4x at detection) | 20% of 59 (day 47, 4.9x at detection) |
| 8x service limit | 64% of 59 (day 47, 7.8x at detection) | 47% of 59 (day 48, 6.3x at detection) | 58% of 59 (day 42, 6.7x at detection) |

### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| AMD | 60 | 2.6% | 0.1% | 0.0% | 0/13 | 18.6% | 95% |
| NAG | 60 | 2.8% | 0.0% | 0.0% | 0/12 | 9.0% | 92% |
| BOM | 60 | 1.8% | 0.0% | 0.0% | 0/13 | 18.3% | 96% |
| GAU | 60 | 4.4% | 0.0% | 0.0% | 0/15 | 18.3% | 93% |
| VTZ | 60 | 2.8% | 0.1% | 1.7% | 2/13 | 16.4% | 95% |
| IXZ | 180 | 2.0% | 0.0% | 0.0% | 0/11 | 9.1% | 73% |
| BHJ | 180 | 4.9% | 0.1% | 0.2% | 1/12 | 17.2% | 70% |
| COK | 180 | 2.4% | 0.0% | 0.0% | 0/9 | 9.4% | 78% |

## FRESH: twelve more stations nobody had looked at, 2020-2024

*Chosen and sealed before the two remedies from the holdout post-mortem were tested (Amendment 2 in config/protocol.md). Eight hourly airport stations and four 3-hourly SYNOP stations.*  Stations: LKO, PAT, IDR, IXR, CJB, IXE, TRZ, ATQ, PNQ, GOI, RPR, JDH.

### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 2.5% (2.5-2.6) of 364440 samples got FAULT or SUSPECT; 0.1% (0.1-0.1) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.1% (0.1-0.2) of 11782 samples (3 of 139 windows); WEATHER on 10.3%, SUSPECT on 6.8% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 99%; spike 91%; level shift 80%; noise burst 57%; dropout 98%; clock 3 h out 85% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 71.1% of 974 NOAA-flagged values (FAULT or SUSPECT alone: 54.9%); escalated on 5.7% of the 375993 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.9% of 18493 station-days; an injected ramp reaching 8x the service limit was found in 62% of trials |

### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 99% | 91% | 80% | 57% | 98% | 85% |
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | 99% | 91% | 80% | 57% | 98% | 85% |
| AtmosGuard + remedy 2 (learned step cap) | 99% | 88% | 80% | 56% | 99% | 81% |
| AtmosGuard + both remedies | 99% | 88% | 80% | 56% | 99% | 81% |
| without physics layer | 99% | 90% | 77% | 54% | 98% | 85% |
| without health layer | 47% | 74% | 72% | 40% | 0% | 68% |
| without normality layer | 99% | 93% | 72% | 56% | 99% | 81% |
| without Isolation Forest | 99% | 91% | 80% | 57% | 98% | 85% |
| without Mahalanobis layer | 99% | 78% | 66% | 46% | 98% | 85% |
| without timing layer | 99% | 91% | 80% | 57% | 98% | 69% |
| without station-learned limits | 75% | 35% | 57% | 62% | 44% | 72% |
| baseline: range check only | 0% | 12% | 13% | 9% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 72% | 78% | 63% | 0% | 94% |
| baseline: climatology z-score only | 27% | 42% | 38% | 9% | 0% | 63% |
| baseline: Isolation Forest only | 1% | 10% | 13% | 11% | 0% | 51% |
| baseline: Mahalanobis distance only | 39% | 99% | 82% | 51% | 0% | 45% |
| (faults injected) | 918 | 918 | 918 | 918 | 918 | 794 |
| AtmosGuard: median minutes to the alarm | 420 | 0 | 0 | 420 | 0 | 1140 |

### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 918 | 99.1% (98.3-99.6) | 89.4% (87.3-91.3) |
| spike | 918 | 91.1% (89.0-92.7) | 18.1% (15.7-20.7) |
| level shift | 918 | 80.3% (77.6-82.7) | 14.3% (12.2-16.7) |
| noise burst | 918 | 57.3% (54.1-60.5) | 9.6% (7.8-11.7) |
| dropout | 918 | 98.4% (97.3-99.0) | 98.4% (97.3-99.0) |
| clock 3 h out | 794 | 85.1% (82.5-87.4) | 1.5% (0.9-2.6) |

### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 99% | 91% | 80% | 57% | 98% | 85% |
| of which named FAULT | 89% | 18% | 14% | 10% | 98% | 2% |
| missed, but made some samples look like WEATHER | 0% | 7% | 10% | 7% | 0% | 9% |

### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 99% | 93% | 84% | 65% | 100% | 87% |
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | 99% | 93% | 84% | 65% | 100% | 87% |
| AtmosGuard + remedy 2 (learned step cap) | 99% | 90% | 82% | 61% | 100% | 82% |
| AtmosGuard + both remedies | 99% | 90% | 82% | 61% | 100% | 82% |
| without physics layer | 99% | 92% | 81% | 62% | 100% | 87% |
| without health layer | 50% | 74% | 74% | 44% | 1% | 68% |
| without normality layer | 99% | 94% | 76% | 62% | 100% | 81% |
| without Isolation Forest | 99% | 93% | 84% | 65% | 100% | 87% |
| without Mahalanobis layer | 99% | 80% | 71% | 54% | 100% | 86% |
| without timing layer | 99% | 93% | 84% | 65% | 100% | 71% |
| without station-learned limits | 100% | 97% | 100% | 99% | 100% | 100% |
| baseline: range check only | 0% | 12% | 13% | 9% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 82% | 94% | 86% | 19% | 94% |
| baseline: climatology z-score only | 32% | 43% | 41% | 13% | 2% | 64% |
| baseline: Isolation Forest only | 6% | 11% | 18% | 18% | 0% | 51% |
| baseline: Mahalanobis distance only | 44% | 99% | 83% | 53% | 0% | 45% |
| (faults injected) | 918 | 918 | 918 | 918 | 918 | 794 |
| AtmosGuard: median minutes to the alarm | 420 | 0 | 0 | 420 | 0 | 1080 |

### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 57% | 2.5% | 3/139 |
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | noise burst: 57% | 2.5% | 2/139 |
| AtmosGuard + remedy 2 (learned step cap) | noise burst: 56% | 2.4% | 2/139 |
| AtmosGuard + both remedies | noise burst: 56% | 2.4% | 1/139 |
| baseline: range check only | frozen: 0% | 0.0% | 0/139 |
| baseline: textbook range + step + persistence | dropout: 0% | 8.4% | 134/139 |
| baseline: climatology z-score only | dropout: 0% | 0.9% | 0/139 |
| baseline: Isolation Forest only | dropout: 0% | 0.4% | 0/139 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.5% | 0/139 |

### The two remedies from the post-mortem, judged by the decision rule registered in Amendment 2

Rule: adopt only if (a) real extreme-weather windows with a FAULT and the FAULT share do not rise, (b) paired detection loses at most 2 points for any injected-fault type, (c) clean false alarms rise by at most 0.2 points. Compared with the frozen `full` pipeline on the same stations.

| configuration | (a) windows with a FAULT (full / this) | (a) FAULT share of extreme-weather samples (full / this) | (b) worst change in paired detection | (c) change in clean false alarms | rule (a) | rule (b) | rule (c) | adopt |
|---|---|---|---|---|---|---|---|---|
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | 3 / 2 of 139 | 0.09% / 0.03% | none | -0.00 pp | pass | pass | pass | yes |
| AtmosGuard + remedy 2 (learned step cap) | 3 / 2 of 139 | 0.09% / 0.08% | -4.2 pp (clock 3 h out) | -0.18 pp | pass | FAIL | pass | no |
| AtmosGuard + both remedies | 3 / 1 of 139 | 0.09% / 0.01% | -4.2 pp (clock 3 h out) | -0.18 pp | pass | FAIL | pass | no |

### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 2.5% | 0.1% | 2.8% | 364440 |
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | 2.5% | 0.0% | 2.8% | 364440 |
| AtmosGuard + remedy 2 (learned step cap) | 2.4% | 0.1% | 2.8% | 364440 |
| AtmosGuard + both remedies | 2.4% | 0.0% | 2.8% | 364440 |
| without physics layer | 2.5% | 0.1% | 2.8% | 364440 |
| without health layer | 0.7% | 0.0% | 1.4% | 364440 |
| without normality layer | 1.4% | 0.1% | 0.8% | 364440 |
| without Isolation Forest | 2.5% | 0.1% | 2.6% | 364440 |
| without Mahalanobis layer | 2.4% | 0.1% | 2.6% | 364440 |
| without timing layer | 2.3% | 0.1% | 2.7% | 364440 |
| without station-learned limits | 63.8% | 25.6% | 0.8% | 364440 |
| baseline: range check only | 0.0% | 0.0% | - | 364440 |
| baseline: textbook range + step + persistence | 8.4% | 8.4% | - | 364440 |
| baseline: climatology z-score only | 0.9% | 0.0% | - | 364440 |
| baseline: Isolation Forest only | 0.4% | 0.0% | - | 364440 |
| baseline: Mahalanobis distance only | 0.5% | 0.0% | - | 364440 |

### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.1% | 6.8% | 10.3% | 82.9% | 3/139 |
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | 0.0% | 6.8% | 10.3% | 82.9% | 2/139 |
| AtmosGuard + remedy 2 (learned step cap) | 0.1% | 6.4% | 10.4% | 83.1% | 2/139 |
| AtmosGuard + both remedies | 0.0% | 6.4% | 10.5% | 83.1% | 1/139 |
| without physics layer | 0.1% | 6.8% | 10.3% | 82.9% | 3/139 |
| without health layer | 0.0% | 2.3% | 5.7% | 92.0% | 0/139 |
| without normality layer | 0.1% | 3.8% | 2.9% | 93.2% | 4/139 |
| without Isolation Forest | 0.1% | 6.7% | 9.7% | 83.5% | 3/139 |
| without Mahalanobis layer | 0.1% | 6.4% | 9.6% | 83.9% | 3/139 |
| without timing layer | 0.1% | 6.7% | 10.2% | 83.0% | 3/139 |
| without station-learned limits | 20.1% | 45.0% | 2.8% | 32.1% | 90/139 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/139 |
| baseline: textbook range + step + persistence | 10.3% | 0.0% | - | 89.7% | 134/139 |
| baseline: climatology z-score only | 0.0% | 4.4% | - | 95.6% | 0/139 |
| baseline: Isolation Forest only | 0.0% | 2.0% | - | 98.0% | 0/139 |
| baseline: Mahalanobis distance only | 0.0% | 1.9% | - | 98.1% | 0/139 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 1898 | 0.0% | 6.0% | 5.2% | 0/19 |
| heat | 1266 | 0.0% | 7.0% | 14.3% | 0/16 |
| low | 4389 | 0.2% | 9.8% | 15.9% | 1/44 |
| sharp | 4229 | 0.1% | 3.9% | 5.6% | 2/60 |

### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 974 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 54.9% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 71.1% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 375993 |
| AtmosGuard alarmed on those (extra flags) | 2.7% |
| AtmosGuard escalated at all on those | 5.7% |

### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 13.5% of 74 chunks | 9.5% of 74 chunks | 16.2% of 74 chunks |
| 1x service limit | 14% of 74 (day 60, 4.1x at detection) | 4% of 74 (day 22, 4.1x at detection) | 9% of 74 (day 145, 5.2x at detection) |
| 2x service limit | 16% of 74 (day 58, 4.6x at detection) | 7% of 74 (day 26, 3.1x at detection) | 18% of 74 (day 73, 4.4x at detection) |
| 4x service limit | 26% of 74 (day 55, 5.6x at detection) | 20% of 74 (day 43, 4.4x at detection) | 31% of 74 (day 52, 5.3x at detection) |
| 8x service limit | 54% of 74 (day 47, 7.7x at detection) | 59% of 74 (day 49, 5.8x at detection) | 73% of 74 (day 52, 7.6x at detection) |

### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| LKO | 60 | 2.1% | 0.0% | 0.0% | 0/11 | 9.9% | 91% |
| PAT | 60 | 2.8% | 0.0% | 0.0% | 0/14 | 8.8% | 94% |
| IDR | 60 | 2.2% | 0.0% | 0.0% | 0/14 | 5.6% | 91% |
| IXR | 60 | 2.0% | 0.0% | 0.5% | 1/13 | 9.1% | 92% |
| CJB | 60 | 2.1% | 0.0% | 0.2% | 1/5 | 3.1% | 95% |
| IXE | 60 | 2.1% | 0.0% | 0.0% | 0/8 | 24.6% | 97% |
| TRZ | 60 | 2.3% | 0.0% | 0.0% | 0/7 | 4.2% | 99% |
| ATQ | 60 | 2.8% | 0.6% | 0.0% | 0/13 | 10.2% | 87% |
| PNQ | 180 | 6.0% | 0.0% | 0.0% | 0/16 | 8.2% | 73% |
| GOI | 180 | 3.2% | 0.0% | 0.0% | 0/12 | 13.3% | 77% |
| RPR | 180 | 3.0% | 0.0% | 0.0% | 0/13 | 20.9% | 71% |
| JDH | 180 | 3.9% | 0.2% | 0.4% | 1/13 | 12.6% | 66% |

## How big must a fault be? (DEV, injected)

How big must a fault be? Spikes, level shifts and noise bursts of 0.25 to 4 times the configured size, injected into clean real data of the six DEV stations (the tuning set, so an envelope study and not a held-out result). A detection is an alarm the fault itself raised. The 1x row is a separate random draw (two faults of each type per series, one round), so it is close to but not identical with the main table.

| system | size (x the configured fault) | spike | level shift | noise burst |
|---|---|---|---|---|
| AtmosGuard | 0.25x | 13% | 2% | 11% |
| AtmosGuard | 0.5x | 70% | 26% | 28% |
| AtmosGuard | 1x | 94% | 94% | 87% |
| AtmosGuard | 2x | 98% | 100% | 100% |
| AtmosGuard | 4x | 98% | 100% | 100% |
| textbook range + step + persistence | 0.25x | 6% | 0% | 13% |
| textbook range + step + persistence | 0.5x | 54% | 24% | 24% |
| textbook range + step + persistence | 1x | 70% | 78% | 69% |
| textbook range + step + persistence | 2x | 98% | 94% | 100% |
| textbook range + step + persistence | 4x | 98% | 100% | 100% |
| Mahalanobis distance only | 0.25x | 9% | 0% | 2% |
| Mahalanobis distance only | 0.5x | 91% | 26% | 24% |
| Mahalanobis distance only | 1x | 100% | 100% | 83% |
| Mahalanobis distance only | 2x | 100% | 100% | 100% |
| Mahalanobis distance only | 4x | 100% | 100% | 100% |

## A new station on day one (cold start)

Leave-one-station-out on the six DEV stations, judged on their DEV years. A starter is a frozen table from the nearest other station. Injected faults: frozen, spike, level shift.

| days of own history | with a starter: clean false alarms | with a starter: FAULT on real extreme weather | with a starter: injected faults detected | own data only: clean false alarms | own data only: FAULT on real extreme weather | own data only: injected faults detected |
|---|---|---|---|---|---|---|
| 0 | 6.09% | 0.0% | 86.4% | 62.72% | 28.6% | 79.6% |
| 30 | 5.79% | 0.0% | 85.8% | 16.53% | 4.97% | 84.0% |
| 90 | 7.34% | 0.0% | 95.7% | 12.83% | 0.03% | 92.0% |
| 365 | 4.17% | 0.0% | 97.5% | 5.3% | 0.0% | 96.9% |
| 1460 | 1.88% | 0.0% | 96.3% | 1.88% | 0.0% | 96.3% |

## Scale (simulated stations, one machine)

Simulated stations on one machine (a design check, not a deployment proof). cpu_count=4, python=3.11.15.

| stations | readings/s | median ms | p95 ms | p99 ms | MB/station | KB stored/station |
|---|---|---|---|---|---|---|
| 1 | 923.8 | 0.921 | 2.368 | 2.787 | 6.92 | 1584.5 |
| 10 | 851.4 | 0.968 | 2.553 | 2.994 | 3.05 | 1584.5 |
| 50 | 836.6 | 0.968 | 2.559 | 3.065 | 2.99 | 1584.5 |
| 100 | 819.0 | 0.986 | 2.555 | 3.109 | 1.78 | 1584.5 |

The same test with the Isolation Forest layer switched off (`layers.mlmodel: false`); the ablation shows it adds almost nothing to the verdicts:

| stations | readings/s | median ms | p95 ms | p99 ms |
|---|---|---|---|---|
| 1 | 1536.9 | 0.499 | 1.713 | 2.071 |
| 50 | 1353.0 | 0.526 | 1.977 | 2.395 |

Real HTTP server (FastAPI + SQLite), 50 stations, 8 concurrent clients: 164.8 requests/s, median 44.89 ms, p95 59.17 ms, p99 66.33 ms, errors 0.
