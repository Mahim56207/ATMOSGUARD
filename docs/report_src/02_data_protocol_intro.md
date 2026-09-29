## 2. Data and evaluation protocol

### 2.1 Data
Records are NOAA Integrated Surface Database (ISD) hourly METAR and 3-hourly SYNOP reports for 14 Indian airports, 2016-2024,
downloaded from NOAA's public open-data bucket. We take temperature, dew point and pressure only. **Humidity is computed from
temperature and dew point** (Magnus formula), because ISD carries no relative humidity. METAR values are rounded to whole degrees and
whole hPa. These are airport observations, not IMD AWS records; every number in this report inherits that caveat. NOAA's own quality
code for each value is kept only as a weak label for an agreement table; it never influences a verdict.

### 2.2 Split
Every station is trained on its own 2016-2019 record with extreme-weather windows and NOAA-flagged values removed. Six stations
(Bhubaneswar, Chennai, Kolkata, Delhi, Jaipur, Thiruvananthapuram) are the **DEV** set: 2020-2021, where tuning was allowed. The
**holdout in time** is the same six stations in 2022-2024. The **holdout in space** is eight stations that were never used for any
tuning: Ahmedabad, Nagpur, Mumbai, Guwahati, Visakhapatnam (hourly) and Port Blair, Bhuj, Cochin (3-hourly SYNOP), 2020-2024.
The protocol (`config/protocol.md`) was committed before the holdout was read; the evaluation program refuses to read the sealed
files unless that file is tracked and unmodified, and it writes a lock file when it runs.

### 2.3 Extreme-weather windows
Windows are chosen by rule on the data, before any verdict is looked at: the deepest low-pressure episodes (at least 10 hPa below
the trailing 30-day median), the hottest and coldest days (top and bottom 0.3 %), and the sharpest 3-hour temperature change of each
year. Real cyclones fall out of the rules without our choosing them: Amphan (Kolkata, 2020) is judged in DEV; Tauktae (Mumbai and
Ahmedabad, 2021), Biparjoy (Bhuj, 2023), Michaung (Chennai, 2023) and Remal (Kolkata, 2024) in the holdouts. Vardah (2016) and Fani (2019)
fall in the training years, so they are cut out of training and used for the demonstration replay, not for a reported number.
A `FAULT` verdict inside such a window is counted as a failure: real weather was called a broken sensor.

### 2.4 The five numbers
1. **Detection of injected faults**, per type (frozen 48 h, spike, level shift 24 h, noise burst 24 h, dropout, clock 3 h out for 4 days).
2. **False alarms on clean real data** (nothing injected).
3. **Real extreme weather** (nothing injected): FAULT, SUSPECT, WEATHER and VALID shares, and windows containing a `FAULT`.
4. **Agreement with NOAA's flags**, described as consistency with another automated system, not accuracy.
5. **Slow drift** through the health monitor, including false drift claims.
plus speed. Each is computed for the full pipeline, for seven ablations (one layer off by its config flag) and for five baselines
(range only; textbook range + step + persistence; climatology z-score only; Isolation Forest only; Mahalanobis distance only), fitted on
the same training data.
