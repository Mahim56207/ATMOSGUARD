## 3. Method

AtmosGuard judges one reading at a time. State is per station; no station ever reads another's live data. Every threshold below
is a value in `config/settings.yaml` (nothing is hard-coded), and every layer has a switch, so the ablation needs no code edits.
The layers are ordered by cost; a fusion step turns their outputs into one of four verdicts.

### 3.1 L0 physics (closed form; also runs on the ESP32)
- **Range:** temperature -90..60 degC, pressure 300..1100 hPa, humidity 0..100 %. Outside is a hard flag.
- **Dew point** (Magnus, a = 17.62, b = 243.12 degC): g = ln(RH/100) + a T/(b+T), Td = b g/(a-g). Td above T + 0.5 degC is a hard flag.
- **Wet-bulb** (Stull 2011). At or above 35 degC it is a **soft** flag only. It is not an "impossible" rule: 35 degC wet-bulb has been observed.

### 3.2 L1 health (per channel; windows are in minutes and scale with the station's cadence)
- **Frozen.** No change over a window. The configured window (T 60, P 180, RH 120 min, at least 3 samples) is stretched to the
  longest run of identical values this station's clean history produced (section 3.3). Two tiers when the window was learned: a
  run past the limit is a **soft** flag; a run `2x` the limit is a **hard** flag.
- **Step / spike.** Allowed change = min(rate x minutes, cap): rates 1 degC, 0.5 hPa, 5 % per minute; caps 10, 10, 40. A spike is a
  one-sample excursion that returns.
- **Noise.** Jitter from **second differences** (which cancel a smooth trend): sqrt(mean(d2^2) / 6), over a window of at least 7 samples.
  Limit: configured (0.5, 0.5, 3.0) or learned, whichever is larger.
- **Gap.** More than 3 cadences since the last reading. Reported as a **notice** on the next reading; it does not change the verdict
  (the values after a gap are fine).
- **CUSUM** on (reading - expected) in normality sigmas, k = 1.5, h = 40, one sample capped at 4 sigma, steps scaled by cadence/15 min.
  A soft flag: real weather anomalies last hours and look like drift.

### 3.3 Station-learned limits (`atmos/limits.py`)
A station that reports whole degrees repeats the same value for hours in ordinary weather. On real Bhubaneswar METAR the fixed
limits alarmed on two thirds of clean samples. For each channel the station's own clean history gives:
the **reporting resolution** (1.0, 0.5, 0.1 or none), the 99.9th percentile of identical-value **run durations**, the 99.9th percentile
of the **noise estimate** (times 1.1), and the **usual step** (75th percentile of |change| between consecutive readings).
The configured values are a floor: learning can only relax a check. The frozen-run idea is HadISD's (streak thresholds from the
distribution of run lengths); the two-tier grading, the resolution detection and the real-time use are ours.

### 3.4 L2 normality (`atmos/normality.py`)
A table of mean, standard deviation and count per station x month x hour (cells with fewer than 10 samples are left out). The
z-score of a reading is (value - mean) / max(std, floor); |z| > 4 is a soft flag. A **smooth expected value** (bilinear in hour and
in month, each month's value taken at mid-month) is used wherever residuals are read over weeks, because the plain table is a step
function and turns the seasonal cycle into a fake trend.

### 3.5 L3 multivariate
- **Isolation Forest** (100 trees, one per station, fixed seed) over the three values, their per-minute changes and the hour as sin/cos;
  alarm below the 0.5 % quantile of the clean training scores.
- **Mahalanobis distance** of the six-vector (departure from the smooth expected value, per-minute change) for each channel, with the
  station's own covariance; alarm above the 99.5 % quantile of the clean training distances. The squared distance splits **exactly**
  into per-feature contributions, so the flag names the channel and feature that drove it.

### 3.6 Timing
- **T1 clock phase:** the daily cycle of the last day is compared with the station's normal cycle at timestamp shifts of -6..+6 whole
  hours; if a non-zero shift cuts the mean squared z by at least half, the clock may be wrong (soft flag). Recomputed every 3 hours of data time.
- **T2 co-jump:** two or more channels exceeding their step limit in the same sample (common-mode glitch). Meaningful only at fast
  cadence; weak on hourly data, and the README says so.

### 3.7 Fusion (first rule that matches wins)
1. A **hard** flag from range, dew point, frozen (at 2x the learned limit) or dropout -> `FAULT`.
2. **One** channel jumps (step or spike) and the other two are **actually quiet** -> `FAULT`. Quiet means each other channel moved by at
   most half of its step allowance over the last two intervals and, once known, at most 1.5x the station's usual step. (Checking only that no
   flag fired was a real bug: a thunderstorm outflow that drops temperature 8 degC fires nothing and made rule 2 call weather a fault.)
3. Only soft flags, and either (a) two or more channels **move** together over the last hour by more than a minimum (T 1 degC,
   P 1 hPa, RH 5 %) in a known pattern (cooling + moistening; warming + drying; falling pressure + rising humidity; rising pressure +
   drying), or (b) two or more channels **depart from normal together** (|z| >= 2) -> `WEATHER`, escalated as an alert.
4. Any other flag -> `SUSPECT` (kept, marked for review).
5. Otherwise `VALID`.

The reason text is built from the checks that fired. **Confidence** is a heuristic agreement score (0.9 valid, 0.95 rule 1, 0.8 rule 2,
0.7 weather, 0.5 suspect, +0.05 per extra supporting soft flag, capped at 0.99). It is **not** a probability and no metric uses it.

### 3.8 Health monitor and drift (`atmos/healthscore.py`)
- **Score** per channel over 7 days = 100 - 100 x (fraction of FAULT verdicts on it) - 50 x (fraction of SUSPECT) - 40 x (drift ratio);
  the station score is the worst channel. `WEATHER` never counts against a sensor.
- **Drift.** Daily means of (reading - smooth expected value), residuals clipped at 3 normality sigmas, samples judged FAULT on that
  channel left out. Over the last 60 days (at least 21 usable days): Theil-Sen slope; significance = OLS slope / a standard error inflated
  by sqrt((1+rho)/(1-rho)), rho the lag-1 autocorrelation of the fit residuals (0..0.9); significant at |z| >= 4.
  **Isolated-trend rule:** if another channel also trends (|z| >= 2.5) the trend is read as a seasonal or weather transition, not drift.
  **Persistence:** significant with the same sign on each of the last 7 daily evaluations.
  The monitor reports the **smallest slope it could see** (z_crit x standard error) so "no drift found" has a stated meaning.
  Service date = when the offset reaches the limit (T 0.5 degC, P 1 hPa, RH 3 %) at the fitted slope.
- **Ticket** when the score is at or below 60, a channel is faulty in at least half of the last hour, or a service date is within 30 days.

### 3.9 Estimate for a missing or faulty value (`atmos/impute.py`)
estimate = normal(t) + rho x (last trusted value - normal(then)), rho = 0.5^(age / 120 min); band = +/- 1.96 sqrt(std^2 (1-rho^2) + (1+rho^2) sigma^2),
sigma the sensor noise floor. It is stored **beside** the raw value; the raw value is never replaced.

### 3.10 Edge (`firmware/node/atmos_l0.h`)
1 Hz sampling, per-sample range check, one-minute mean of the valid samples (at least 30), dew point vs temperature, and a counter of identical
minute means (30 in a row -> frozen flag), with a queue of 30 unsent minutes while the network is down. The header is plain C++11
with no Arduino dependency, so the same code is compiled and compared with the Python implementation on thousands of inputs
(`tests/test_edge_parity.py`). It has not been run on hardware.

### 3.11 Cold start (`atmos/coldstart.py`)
A new station borrows the frozen table and limits of the nearest other station and blends them cell by cell with its own as its own
data grows (weight = samples in the cell / 30; limits over 365 days). No live neighbour data is read.
