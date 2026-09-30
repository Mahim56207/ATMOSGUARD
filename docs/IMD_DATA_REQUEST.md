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

## If they cannot send the file: send the code instead
Many organisations will not release raw AWS records but will run a program on them. [`IMD_RUN_IT_YOURSELF.md`](IMD_RUN_IT_YOURSELF.md) is a one-page version of this request for that case: they run one command on their own machine and send back only counts and rates (no readings, no timestamps).
Offer it in the same email: "If the files cannot leave IMD, we can send the code and you run it yourselves; what comes back is a small JSON of counts and rates."

## If the file is not in our layout
IMD downloads and logger exports come in many layouts. `python -m data_tools.adapt_csv raw_file --out data/uploads/aws.csv --tz IST` converts almost any of them (column names, units, separate date and time columns, Excel serial dates, local time to UTC, missing-value codes,
several stations in one file) and prints every decision it makes; `--inspect` shows them without writing anything.

## If nobody replies in time
Say so plainly: "records of IMD AWS stations are not public and we did not obtain one; we tested on airport METAR and on Australian Bureau of Meteorology automatic weather stations
(hourly SYNOP at 0.1 resolution), and `evaluate_csv.py` will run the same evaluation on an IMD file in one command."

---

## Ready to send (copy, fill the brackets, send)

**Who to send it to, in order of what usually works:** (1) your faculty mentor or department head, asking them to forward it or introduce you to someone at IMD; (2) the IMD data-supply channel listed on IMD's own website (check
the current address there; data supply is normally handled by the National Data Centre in Pune and the regional meteorological centres); (3) any IMD or state-government AWS contact your college or the SIH nodal centre can introduce. Do not
guess email addresses.

**Subject:** Request for a small sample of AWS data (temperature, pressure, humidity) to test a student sensor-health system, Smart India Hackathon PS 26073

**Email:**

> Respected Sir/Madam,
>
> We are [team name], students of [college], participating in the Smart India Hackathon (problem statement 26073: anomaly detection and sensor health for an Automatic Weather Station using temperature, pressure and humidity only).
> Our open-source system, AtmosGuard (github.com/Mahim56207/ATMOSGUARD), tells a failing sensor from real extreme weather using one station's own readings. It has been evaluated on real airport and automatic-station records
> from public archives, but not on IMD AWS data, because that data is not public.
>
> We would be grateful for a small sample: **the raw records of one or two AWS stations for at least three years** (UTC timestamp, temperature, pressure, relative humidity; any cadence from 1 to 60 minutes), ideally with **any maintenance log or
> quality-control flags** for the same period. We will use the data only to evaluate the system, publish only aggregate results (false-alarm rate, behaviour in real cyclones and heat waves, detection of injected faults), keep the files private,
> and share the results with you. If a full record is not possible, even a few months from a coastal station that experienced a cyclone would help.
>
> Our evaluation code runs on any such file with one command, so we can return results within a day. Thank you for your time.
>
> [names, college, phone, email]

**Short version (WhatsApp / message to a mentor):** "Sir, could you help us get a small sample of real IMD AWS data (T, P, RH, 1-3 years, one or two stations, maintenance log if possible)? We built a sensor-fault detector for SIH PS 26073 and want to test it on real IMD records. Code: github.com/Mahim56207/ATMOSGUARD. We will keep it private and share the results."

**If they say yes:** save the file as CSV with columns `timestamp,temperature_c,pressure_hpa,humidity_pct` (UTC) and run `python evaluate_csv.py file.csv --station NAME`; add `--quick` for a faster one-year pass.
