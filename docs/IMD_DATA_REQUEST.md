# Asking for a real IMD AWS record (a draft you can send)

The evaluation uses NOAA records because those could be downloaded in advance. The problem statement is about IMD's automatic weather stations, whose records are not public.
One real file would turn the biggest caveat of this project into a result, on the same code, with one command. This page is a message you can adapt and send to a mentor,
your institute's IMD contact, or IMD's data supply unit, and what to do when a file arrives.

## What to ask for (one paragraph)
> We are a student team working on anomaly detection and sensor health for automatic weather stations (problem statement 26073) from temperature, pressure and humidity
> alone. To test it on real AWS data we would like the raw records of **one or two AWS stations for at least three years**, ideally with **any maintenance log or quality-control
> flag** for the same period. Columns needed: UTC timestamp, temperature, pressure (station level is fine; say which), relative humidity. A different cadence (1, 5, 10, 15
> minutes) is fine. We will use the data only for evaluation, report only aggregate results (false-alarm rate, detection of injected faults, what happens in real extreme
> weather), keep the file private, and share the result with you.

## Why three years
The station's own normality table is month x hour, so every month needs data, and the first part of the record trains the station-learned limits. `evaluate_csv.py` warns when
the record is shorter and says what it found.

## When a file arrives (five minutes)
```bash
python evaluate_csv.py path/to/aws.csv --station MYAWS                       # the full tables, baselines and ablations on this station
python evaluate_csv.py path/to/aws.csv --station MYAWS --train-fraction 0.6 --quick   # faster, one year judged
```
- If the record has maintenance dates, replay those days (`python replay.py path/to/aws.csv --station MYAWS`, or the dashboard's **Control panel**) and read the verdict timeline for
  them. That is the first evidence on real faults; write down what the pipeline said, including if it said nothing.
- If the numbers are worse than ours, that is useful, and `docs/FAILURE_MODES.md` lists what to check first (reporting resolution, cadence, humidity saturation, an unflagged fault inside the training years).
- Put the file in `data/uploads/` only if it may be shared; `data/uploads/` is git-ignored, so it stays on your machine.

## If nobody replies in time
Say so plainly: "records of IMD AWS stations are not public and we did not obtain one; we tested on airport METAR and on Australian Bureau of Meteorology automatic weather stations
(hourly SYNOP at 0.1 resolution), and `evaluate_csv.py` will run the same evaluation on an IMD file in one command."
