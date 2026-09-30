# Testing AtmosGuard on IMD data without the data ever leaving IMD

The usual blocker for testing on AWS records is not willingness, it is that the raw files cannot be sent out. So the request can be turned around: **we send the code, IMD runs it on its own machine, and only counts and rates come back.**
This page is written to be forwarded to someone at IMD (or a state AWS network) who is not a programmer; the last section is for whoever runs it.

## What would be run, and what comes out
- One command evaluates one station record that is already on the machine. It reads the file, fits the station's own models on the first part of the record, and judges the rest, including real cyclones and heat waves found by fixed rules in the file itself.
- Nothing is uploaded. The program opens no network connection while it runs (the `data/uploads/` folder it may use is git-ignored).
- What is saved is **counts and rates only**: false alarms on clean data, what happened in real extreme weather, how many injected faults were caught (by type), speed, learned limits. No readings, no example values, no timestamps. The file is plain JSON that can be opened and read in full before it is sent anywhere
  (`--aggregates-out`; the code that strips everything else is `evaluate_csv.aggregates_only`, and `tests/test_adapt_csv.py` checks it).
- It also prints a verdict timeline for any dates IMD names (for example known maintenance days), if asked to.

## What is needed, at the least
1. One AWS station, **two to three years** of readings (a cyclone-exposed coastal station is the most informative), any cadence from 1 to 60 minutes.
2. Temperature, pressure (station level or sea level, say which) and relative humidity, and a timestamp (say whether it is UTC or IST).
3. Optionally: any quality-control flag column, and the dates of maintenance or known sensor faults. Those dates are the only real labels this project has never had.

## For whoever runs it
```bash
git clone https://github.com/Mahim56207/ATMOSGUARD && cd ATMOSGUARD
pip install -r requirements.txt            # or: docker build -t atmosguard .   (then run the same commands inside it)
# 1. look at what the tool understands about your file, and write nothing:
python -m data_tools.adapt_csv path/to/your_file.csv --inspect            # also reads .xlsx (pip install openpyxl)
# 2. convert it (add --tz IST if the times are local; --pressure-column NAME etc. if it guesses wrong):
python -m data_tools.adapt_csv path/to/your_file.csv --out data/uploads/aws.csv --tz IST
# 3. evaluate; the aggregate file is the only thing to send back:
python evaluate_csv.py data/uploads/aws.csv --station MYAWS --aggregates-out aggregates_MYAWS.json
```
It takes roughly ten to thirty minutes for three years of hourly data on an ordinary laptop, depending on the machine (a 5-minute record takes longer; add `--quick` for one year). The adapter prints every assumption it made (which column is which, units, time zone, missing-value codes) and
stops with a message that says what to pass if it cannot decide. If the numbers are worse than the ones in `results/REPORT.md`, that is the useful outcome: `docs/FAILURE_MODES.md` says what to check first, and the aggregate file is enough for us to work from.

## What we will do with the result
Report it as what it is: one station, real instrument, not sealed, with the airport and Australian automatic-station results next to it, and credit IMD. If it is worse, we will say that in the same place.
