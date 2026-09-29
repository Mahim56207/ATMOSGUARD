# Use your own data (for example a real IMD AWS record)

Everything we report comes from NOAA airport records, because that is what could be downloaded and sealed in advance. The
problem statement is about **Automatic Weather Stations**. If your team, a judge, or an IMD contact can supply a few years of a
real AWS record, one command gives the same numbers for that station, on the same code.

```bash
python evaluate_csv.py path/to/aws.csv --station MYAWS
python evaluate_csv.py path/to/aws.csv --station MYAWS --train-fraction 0.6 --quick      # faster, one year judged
```

## What the file must look like
| Column | Rule |
|---|---|
| `timestamp` | UTC. A timestamp with a zone is converted. Sorted or not, duplicates are dropped |
| `temperature_c`, `pressure_hpa`, `humidity_pct` | numbers; an empty cell is a missing value |
| `station_id` | optional (replaced by `--station`) |
| `noaa_flag` | optional; `0` = fine. Any quality flag you have can be put here (0 fine, higher = worse) and is reported separately |

At least about **two years** are needed so every month has data (the normality table is station x month x hour). The script warns
when the record is shorter and says what it found: cadence, the split date, and how many extreme-weather windows it will judge.

## What it does
1. The first `--train-fraction` of the record **in time** fits the station's own models: normality table, Isolation Forest,
   Mahalanobis model, and the station-learned limits (resolution, frozen-run length, noise, usual step).
2. Extreme-weather windows are found on your data by the **same objective rules** as for the NOAA stations (deepest low-pressure
   episodes, hottest and coldest days, sharpest 3-hour changes, see `config/protocol.md`). Windows before the split are cut out of
   training; windows after it are judged.
3. The rest of the record is judged exactly as in `evaluate_real.py`: false alarms on clean data, what real extreme weather gets
   (a `FAULT` there is a failure), detection of injected faults (paired, so background alarms are not credited), slow-drift power and
   false drift claims, agreement with your flag column, plus every baseline and every ablation.

## What it is not
It is a **check on your station, not a sealed holdout**: nothing about a file you supply is hidden from anyone. It also does not
create labels. If the record contains real, known faults, list their dates and read the verdict timeline for those dates
(`replay.py`, or the dashboard's Control panel) rather than trusting the injected-fault table.

## If the numbers on your station are worse than ours
That is useful information and it is the expected failure mode; see [`FAILURE_MODES.md`](FAILURE_MODES.md). The first things to
check, in order:
1. **Reporting resolution.** Airport METAR is whole degrees and whole hPa; a real AWS usually reports 0.1. The learned limits detect
   whichever one it is (`atmos/limits.py`). Our 3-hourly SYNOP stations (Port Blair, Bhuj, Cochin in the first holdout; Pune, Goa, Raipur, Jodhpur in
   the fresh set) report 0.1 C and 0.1 hPa, so fine resolution has been exercised, but at 3-hour cadence. A fine-resolution record at 1 to
   15-minute cadence is the case we have not tested.
2. **Cadence.** The script uses the median gap between readings and prints it. A record with irregular or mixed cadence (a station that
   switches from hourly to half-hourly) should be split into one CSV per cadence. This is not hypothetical: four of the seven Australian AWS in the third sealed set reported 16 times a day with
   alternating 1 h and 2 h gaps for their first four years and hourly all day after, no noise limit could be learned, and they got 8-33 % false alarms until refitted at the current cadence. The pipeline
   prints an informational `limits` notice on every reading when a noise limit is missing or the cadence differs from the one the limits were learned at: if you see it, refit on a stretch at the current cadence.
3. **Humidity.** If your RH comes from a capacitive sensor that saturates at 100 %, a run of `100` is real and the learned frozen limit
   will reflect it; if it does not, look at the frozen tier the alarm names.
4. **Record quality.** A long real fault that nobody flagged inside the training years is learned as "normal". Cut it out of the CSV.

## Watch it judge your file, live
Start the API and the dashboard (`make api`, `make dashboard`), open the **Control panel**, and use **Bring your own CSV**. The file is saved on the
server under `data/uploads/` and judged through the same pipeline, at the speed you choose. Two things to know:

- **A station the server has no models for learns from the first half of the file** (at least two weeks, at least 300 usable readings), then the second half is
  judged. Without that the fixed limits would judge it, and they alarm on most clean rounded data. Anything abnormal in the first half is learned as normal,
  so give it a stretch you trust. Untick the box to judge everything with whatever models exist. The same thing from a script:
  `POST /replay/upload` with `{"filename": ..., "text": <the CSV>, "learn_fraction": 0.5}`.
- **A station id the server already knows** (BBI, MAA, CCU, DEL, JAI, TRV) is judged with its committed models from the first reading.

On a real station's file (Chennai, 2016-2021, renamed so the server treated it as new) the second half came out 96 % `VALID`, 2 % `WEATHER`, 2 % `SUSPECT` and no
`FAULT`, which is what the evaluation says to expect. That is a functional check on the tuning set, not a result.

