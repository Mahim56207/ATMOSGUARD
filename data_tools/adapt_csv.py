"""Turn a station file in almost any layout (an IMD download, a logger export, an Excel sheet) into the CSV AtmosGuard reads.

    python -m data_tools.adapt_csv raw_download.xlsx --out data/uploads/aws.csv
    python -m data_tools.adapt_csv raw.csv --out aws.csv --tz +05:30 --pressure-column "STN PRES" --station-column "STATION"
    python -m data_tools.adapt_csv raw.csv --inspect                      # print what it would do and stop

The target is `timestamp,temperature_c,pressure_hpa,humidity_pct` (UTC, ISO), plus `station_id` when the file holds more than one station (one output file per station) and
`noaa_flag` when the file has a quality-flag column (0 = fine, anything else = flagged). It never guesses silently: every decision (which column, which unit, which time zone,
which missing-value code) is printed, and anything it cannot decide stops it with a message that says what to pass.

What it understands
  columns     common names for the three channels and the time (TEMP, Temp (C), AIR_TEMPERATURE, T, TT, DRYBULB; MSLP, STN_PRES, PRESSURE, QFE, QNH, P; RH, HUMIDITY, RELATIVE HUMIDITY, %RH; DATE + TIME,
              DATETIME, TIMESTAMP, OBS_TIME), matched case-insensitively ignoring spaces, units in brackets and punctuation
  units       temperature in C, F or K; pressure in hPa, mbar, Pa, kPa, hectopascal, mmHg or inHg; humidity in % or as a fraction 0-1; chosen from the column name when it says so, otherwise from the values
  time        ISO, day-first (31/12/2024 23:30) or month-first dates, separate date and time columns, Excel serial numbers, and a zone: --tz +05:30 (or IST) says the times are local and converts to UTC.
              Without --tz the times are taken as UTC and that is printed.
  missing     empty, NA, NaN, null, -, ---, -999, -9999, 9999, 99999, 999.9 and --missing CODE
  layout      .csv, .tsv, .txt (delimiter sniffed) and .xlsx (needs `pip install openpyxl`, used only here)
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

CHANNEL_NAMES = {
    "temperature_c": ("temperature", "temp", "airtemperature", "airtemp", "ambienttemperature", "drybulb", "drybulbtemperature", "tdry", "tt", "t", "tair", "tempc", "temperaturec", "ta"),
    "pressure_hpa": ("pressure", "pres", "press", "stnpres", "stationpressure", "stationlevelpressure", "mslp", "msl", "slp", "qfe", "qnh", "atmosphericpressure", "baro", "barometer", "p", "pressurehpa"),
    "humidity_pct": ("humidity", "rh", "relativehumidity", "relhum", "relhumidity", "hum", "humiditypct", "rhpct", "rhum"),
}
TIME_NAMES = ("timestamp", "datetime", "datetimeutc", "datetimeist", "obstime", "observationtime", "time", "date", "dateandtime", "datetimestamp", "utc", "obsdatetime")
DATE_ONLY = ("date", "obsdate", "day", "observationdate")
TIME_ONLY = ("time", "obstimeofday", "hhmm", "hour", "timeutc", "timeist", "timeofobservation")
STATION_NAMES = ("station", "stationid", "stationname", "stn", "stncode", "stationcode", "awsid", "awsname", "site", "siteid", "name")
FLAG_NAMES = ("qc", "qcflag", "flag", "qualityflag", "quality", "noaaflag", "qf")
MISSING_CODES = {"", "na", "nan", "n/a", "null", "none", "-", "--", "---", "----", "m", "missing", "nd"}
MISSING_NUMBERS = (-999.0, -9999.0, -99.0, 9999.0, 99999.0, 999.9, -999.9, 9999.9, 99.9)
UNIT_SUFFIXES = ("k", "f", "c", "degc", "degf", "pa", "hpa", "kpa", "mb", "mbar", "pct", "percent", "inhg", "mmhg", "frac", "fraction")
TZ_ALIASES = {"utc": 0.0, "gmt": 0.0, "z": 0.0, "ist": 5.5, "india": 5.5}


def norm(name: str) -> str:
    """A column name reduced to lower-case letters and digits, without a bracketed unit."""
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", "", str(name)).lower()
    return re.sub(r"[^a-z0-9]", "", s)


def unit_hint(name: str) -> str:
    return str(name).lower()


class AdaptError(SystemExit):
    pass


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            raise AdaptError("Reading Excel needs openpyxl: pip install openpyxl (only this tool uses it). Or save the sheet as CSV.")
        return pd.read_excel(path, dtype=object)
    if suffix == ".xls":
        raise AdaptError("Old .xls files are not read. Save the sheet as .xlsx or CSV.")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|")
        sep = dialect.delimiter
    except csv.Error:
        sep = ","
    return pd.read_csv(path, sep=sep, dtype=object, encoding="utf-8-sig", skipinitialspace=True, engine="python")


def find_column(columns: list[str], names: tuple[str, ...], used: set[str], override: Optional[str] = None) -> Optional[str]:
    if override:
        if override not in columns:
            raise AdaptError(f"No column named {override!r}. The file has: {', '.join(map(str, columns))}")
        return override
    normed = {c: norm(c) for c in columns if c not in used}
    for want in names:                                        # names are in order of preference: exact match first
        for c, n in normed.items():
            if n == want:
                return c
    for want in names:                                        # then a unit glued on the end ("Temp K", "Pressure Pa", "RH pct")
        for c, n in normed.items():
            if any(n == want + u for u in UNIT_SUFFIXES):
                return c
    return None


def to_numeric(series: pd.Series, extra_missing: tuple[str, ...] = ()) -> pd.Series:
    s = series.astype("string").str.strip()
    blank = s.str.lower().isin(MISSING_CODES | {m.lower() for m in extra_missing})
    x = pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")       # a decimal comma
    x = x.mask(blank)
    return x


def apply_missing_numbers(x: pd.Series, extra: list[float]) -> tuple[pd.Series, list[float]]:
    hit = []
    for code in (*MISSING_NUMBERS, *extra):
        n = int((x == code).sum())
        if n and (code in extra or n >= max(3, 0.0005 * len(x))):       # a lone -99.0 can be a real value; a code repeated is a missing-value marker
            hit.append(code)
            x = x.mask(x == code)
    return x, hit


def convert_temperature(x: pd.Series, name: str, notes: list[str]) -> pd.Series:
    h = unit_hint(name)
    if re.search(r"(\bk\b|kelvin|\(k\))", h) or (x.dropna().median() > 200 and x.dropna().median() < 340):
        notes.append(f"temperature: values look like kelvin ({name}); converted to C (minus 273.15)")
        return x - 273.15
    if re.search(r"(\bf\b|fahrenheit|\(f\)|degf)", h) or (x.dropna().median() > 45 and x.dropna().max() < 140):
        notes.append(f"temperature: values look like Fahrenheit ({name}); converted to C")
        return (x - 32.0) * 5.0 / 9.0
    notes.append(f"temperature: taken as degrees C ({name}); median {x.dropna().median():.1f}")
    return x


def convert_pressure(x: pd.Series, name: str, notes: list[str]) -> pd.Series:
    h = unit_hint(name)
    med = float(x.dropna().median())
    if re.search(r"(inhg|in hg|inches)", h) or 25.0 < med < 32.5:
        notes.append(f"pressure: inches of mercury ({name}); converted to hPa (x 33.8639)")
        return x * 33.8639
    if re.search(r"mmhg", h) or 500.0 < med < 800.0 and re.search(r"mm", h):
        notes.append(f"pressure: mm of mercury ({name}); converted to hPa (x 1.33322)")
        return x * 1.33322
    if re.search(r"\bkpa\b|\(kpa\)", h) or 60.0 < med < 110.0:
        notes.append(f"pressure: kPa ({name}); converted to hPa (x 10)")
        return x * 10.0
    if re.search(r"\bpa\b|\(pa\)", h) or 60000.0 < med < 110000.0:
        notes.append(f"pressure: Pa ({name}); converted to hPa (/ 100)")
        return x / 100.0
    notes.append(f"pressure: taken as hPa or mbar ({name}); median {med:.1f}")
    return x


def kind_of_pressure(name: str) -> str:
    n = norm(name)
    if n in ("mslp", "msl", "slp", "qnh"):
        return "sea-level (MSLP/QNH): fine, the models learn the station's own level"
    if n in ("stnpres", "stationpressure", "stationlevelpressure", "qfe"):
        return "station level: fine"
    return "unspecified"


def convert_humidity(x: pd.Series, name: str, notes: list[str]) -> pd.Series:
    mx = float(x.dropna().max()) if x.notna().any() else 0.0
    if mx <= 1.5 and float(x.dropna().median()) <= 1.0:
        notes.append(f"humidity: a fraction 0-1 ({name}); converted to percent (x 100)")
        return x * 100.0
    notes.append(f"humidity: percent ({name})")
    return x


def parse_zone(tz: Optional[str]) -> float:
    if tz is None:
        return 0.0
    t = tz.strip().lower()
    if t in TZ_ALIASES:
        return TZ_ALIASES[t]
    m = re.fullmatch(r"([+-])(\d{1,2})(?::?(\d{2}))?", t)
    if not m:
        raise AdaptError(f"Cannot read --tz {tz!r}. Use UTC, IST, or an offset like +05:30 (hours east of UTC).")
    hours = int(m.group(2)) + (int(m.group(3)) / 60.0 if m.group(3) else 0.0)
    return hours if m.group(1) == "+" else -hours


def parse_times(df: pd.DataFrame, time_col: Optional[str], date_col: Optional[str], clock_col: Optional[str], dayfirst: Optional[bool],
                tz_hours: float, notes: list[str]) -> pd.Series:
    if time_col is not None:
        raw = df[time_col]
        what = time_col
    elif date_col is not None and clock_col is not None:
        raw = df[date_col].astype("string").str.strip() + " " + df[clock_col].astype("string").str.strip()
        what = f"{date_col} + {clock_col}"
    elif date_col is not None:
        raw, what = df[date_col], date_col
    else:
        raise AdaptError("No time column found. Pass --time-column NAME (or --date-column and --clock-column).")
    num = pd.to_numeric(raw, errors="coerce")
    if num.notna().mean() > 0.9 and num.dropna().between(20000, 80000).all():                    # an Excel serial date
        ts = pd.to_datetime("1899-12-30") + pd.to_timedelta(num, unit="D")
        notes.append(f"time: {what} holds Excel serial numbers; converted")
    else:
        sample = raw.dropna().astype(str).head(2000)
        if dayfirst is None:
            dayfirst = bool(sample.str.match(r"^\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}").mean() > 0.5)       # 31/12/2024 style
            if dayfirst:
                first = sample.str.extract(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.]")
                a, b = pd.to_numeric(first[0]), pd.to_numeric(first[1])
                if (b > 12).any() and not (a > 12).any():
                    dayfirst = False                                                                    # the second number exceeds 12, so it is the day: month-first
                    notes.append("time: dates are month-first (the second number goes above 12)")
                elif (a > 12).any():
                    notes.append("time: dates are day-first (the first number goes above 12)")
                else:
                    notes.append("time: dates like 01/02/2024 are ambiguous; taken as DAY-first. Pass --month-first if they are not")
        ts = pd.to_datetime(raw, errors="coerce", dayfirst=dayfirst)
        if ts.dt.tz is not None:
            ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
            tz_hours = 0.0
            notes.append(f"time: {what} carries its own zone; converted to UTC")
    bad = int(ts.isna().sum())
    if bad > 0.05 * len(ts):
        raise AdaptError(f"{bad} of {len(ts)} times could not be read from {what}. Example: {raw[ts.isna()].iloc[0]!r}. Say how they are written with --time-column / --date-column / --clock-column.")
    ts = ts - pd.to_timedelta(tz_hours, unit="h")
    notes.append(f"time: {what}; taken as UTC" if tz_hours == 0.0 else f"time: {what}; local time {tz_hours:+g} h, converted to UTC")
    return ts


def adapt(df: pd.DataFrame, *, tz: Optional[str] = None, time_column: Optional[str] = None, date_column: Optional[str] = None, clock_column: Optional[str] = None,
          temperature_column: Optional[str] = None, pressure_column: Optional[str] = None, humidity_column: Optional[str] = None, station_column: Optional[str] = None,
          flag_column: Optional[str] = None, missing: Optional[list[str]] = None, dayfirst: Optional[bool] = None) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """(one frame per station in the layout AtmosGuard reads, what was decided). Raises AdaptError when something cannot be decided."""
    notes: list[str] = []
    cols = [str(c) for c in df.columns]
    df = df.rename(columns={c: str(c) for c in df.columns})
    used: set[str] = set()
    found = {}
    for ch, names in CHANNEL_NAMES.items():
        override = {"temperature_c": temperature_column, "pressure_hpa": pressure_column, "humidity_pct": humidity_column}[ch]
        c = find_column(cols, names, used, override)
        if c is None:
            raise AdaptError(f"No column found for {ch}. The file has: {', '.join(cols)}. Pass --{ch.split('_')[0]}-column NAME.")
        found[ch] = c
        used.add(c)
    time_col = find_column(cols, TIME_NAMES, used, time_column) if not (date_column or clock_column) else None
    date_col = find_column(cols, DATE_ONLY, used, date_column) if time_col is None else None
    clock_col = find_column(cols, TIME_ONLY, used | ({date_col} if date_col else set()), clock_column) if time_col is None else None
    if time_col is not None and time_col in (date_col, clock_col):
        date_col = clock_col = None
    if time_col is not None and norm(time_col) in TIME_ONLY and norm(time_col) != "time" and date_col is None:
        pass
    # "date" and "time" as two columns
    if time_col is not None and norm(time_col) == "time":
        d = find_column(cols, DATE_ONLY, used | {time_col}, date_column)
        if d is not None:
            time_col, date_col, clock_col = None, d, time_col
    station_col = find_column(cols, STATION_NAMES, used | {c for c in (time_col, date_col, clock_col) if c}, station_column)
    flag_col = find_column(cols, FLAG_NAMES, used | {c for c in (station_col,) if c}, flag_column)
    extra_text = tuple(missing or ())
    extra_num = []
    for m in extra_text:
        try:
            extra_num.append(float(m))
        except ValueError:
            pass

    out = pd.DataFrame(index=df.index)
    out["timestamp"] = parse_times(df, time_col, date_col, clock_col, dayfirst, parse_zone(tz), notes)
    if tz is None:
        notes.append("time zone: none given, so the times are taken as UTC. IMD files are often in IST: if yours are, run again with --tz IST")
    codes: list[float] = []
    for ch in ("temperature_c", "pressure_hpa", "humidity_pct"):
        x = to_numeric(df[found[ch]], extra_text)
        x, hit = apply_missing_numbers(x, extra_num)
        codes += hit
        if not x.notna().any():
            raise AdaptError(f"Column {found[ch]!r} has no numbers in it.")
        x = {"temperature_c": convert_temperature, "pressure_hpa": convert_pressure, "humidity_pct": convert_humidity}[ch](x, found[ch], notes)
        out[ch] = x
    if codes:
        notes.append("missing values: " + ", ".join(f"{c:g}" for c in sorted(set(codes))) + " treated as missing (repeated sentinel codes)")
    notes.append(f"pressure kind: {kind_of_pressure(found['pressure_hpa'])}")
    if flag_col is not None:
        f = pd.to_numeric(df[flag_col], errors="coerce")
        if f.notna().mean() > 0.9:
            out["noaa_flag"] = (f.fillna(0) != 0).astype(int)
            notes.append(f"quality flag: {flag_col}; 0 is fine, anything else is flagged (reported separately, never used for a verdict)")
        else:
            notes.append(f"quality flag: {flag_col} is not numeric, so it was not used")
    # sanity: physical plausibility after conversion
    for ch, lo, hi in (("temperature_c", -90, 65), ("pressure_hpa", 300, 1100), ("humidity_pct", 0, 105)):
        v = out[ch].dropna()
        bad = int(((v < lo) | (v > hi)).sum())
        if bad > 0.02 * len(v):
            raise AdaptError(f"After conversion {bad} of {len(v)} {ch} values are outside [{lo}, {hi}]. The unit or column is probably wrong: check {found[ch]!r}.")
        if bad:
            notes.append(f"{ch}: {bad} values outside [{lo}, {hi}] were kept (the pipeline's range check will call them faults)")
    out = out.dropna(subset=["timestamp"])
    if station_col is not None:
        out["station_id"] = df.loc[out.index, station_col].astype("string").str.strip()
        names = [s for s in out["station_id"].dropna().unique()]
        notes.append(f"stations: {len(names)} in column {station_col}: {', '.join(map(str, names[:8]))}{' ...' if len(names) > 8 else ''}")
    else:
        out["station_id"] = "STATION"
    result = {}
    for sid, g in out.groupby("station_id"):
        g = g.drop(columns="station_id").sort_values("timestamp")
        dups = int(g["timestamp"].duplicated().sum())
        g = g.drop_duplicates("timestamp")
        if dups:
            notes.append(f"{sid}: {dups} duplicate timestamps dropped (first kept)")
        g["timestamp"] = g["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
        cad = pd.to_datetime(g["timestamp"]).diff().dt.total_seconds().div(60).median()
        span = (pd.to_datetime(g["timestamp"]).iloc[-1] - pd.to_datetime(g["timestamp"]).iloc[0]).days if len(g) > 1 else 0
        notes.append(f"{sid}: {len(g)} readings, {span} days, median gap {cad:g} min")
        if span < 700:
            notes.append(f"{sid}: only {span} days; the month-by-hour table wants about two years, so results will be weak")
        result[str(sid)] = g.reset_index(drop=True)
    return result, notes


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, help="output CSV (with several stations: one file per station, the station id added to the name)")
    ap.add_argument("--inspect", action="store_true", help="print what would be done and write nothing")
    ap.add_argument("--tz", help="the zone the times are in: UTC (default), IST, or an offset such as +05:30")
    ap.add_argument("--time-column"), ap.add_argument("--date-column"), ap.add_argument("--clock-column")
    ap.add_argument("--temperature-column"), ap.add_argument("--pressure-column"), ap.add_argument("--humidity-column")
    ap.add_argument("--station-column"), ap.add_argument("--flag-column")
    ap.add_argument("--missing", action="append", help="an extra missing-value code (repeatable)")
    ap.add_argument("--month-first", action="store_true", help="dates like 01/02/2024 are month/day")
    a = ap.parse_args(argv)
    df = read_table(a.input)
    frames, notes = adapt(df, tz=a.tz, time_column=a.time_column, date_column=a.date_column, clock_column=a.clock_column, temperature_column=a.temperature_column,
                          pressure_column=a.pressure_column, humidity_column=a.humidity_column, station_column=a.station_column, flag_column=a.flag_column,
                          missing=a.missing, dayfirst=False if a.month_first else None)
    print(f"{a.input}: {len(df)} rows, columns: {', '.join(map(str, df.columns))}")
    for n in notes:
        print("  " + n)
    if a.inspect or not a.out:
        print("(nothing written)" if a.inspect else "(no --out given, nothing written)")
        return 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    for sid, g in frames.items():
        path = a.out if len(frames) == 1 else a.out.with_name(f"{a.out.stem}_{re.sub(r'[^A-Za-z0-9_-]', '_', sid)}{a.out.suffix}")
        g.to_csv(path, index=False, float_format="%.3f")
        print(f"wrote {path}  ->  python evaluate_csv.py {path} --station {re.sub(r'[^A-Za-z0-9_-]', '_', sid)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
