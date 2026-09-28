# Data

## Source
NOAA Integrated Surface Database (ISD), "global hourly" open-data bucket
(`https://noaa-global-hourly-pds.s3.amazonaws.com/<year>/<USAF><WBAN>.csv`). Public, no key. Station coordinates and
elevation are from NOAA's own station history file.

## What we take from each report (and nothing else)
| Channel | METAR (FM-15) | SYNOP (FM-12) |
|---|---|---|
| temperature_c | TMP, whole degrees C | TMP, 0.1 C |
| humidity_pct | computed from TMP and DEW (Magnus, Alduchov-Eskridge). **ISD carries no RH.** | same |
| pressure_hpa | altimeter setting (QNH), whole hPa | sea-level pressure, 0.1 hPa |

Wind, rain, visibility, cloud and every other field are ignored. NOAA's own quality code for each value is kept as
`noaa_flag` (0 none, 1 suspect, 2 erroneous). It is **never** used to make a verdict; it is only the weak label for the
agreement table.

## Stations (14)
Hourly METAR: Bhubaneswar (BBI), Chennai (MAA), Kolkata (CCU), Delhi (DEL), Jaipur (JAI), Thiruvananthapuram (TRV) -
**DEV stations**; Ahmedabad (AMD), Nagpur (NAG), Mumbai (BOM), Guwahati (GAU), Visakhapatnam (VTZ) - **sealed**.
3-hourly SYNOP, all **sealed**: Port Blair (IXZ), Bhuj (BHJ), Cochin (COK). Climate zones, coordinates and cadence are in
`config/stations.yaml`. Leh and Hyderabad were dropped (too few reports); Srinagar had no pressure group.

## Split
| Set | What | Used for |
|---|---|---|
| Training | each station's own 2016-2019, extreme-weather windows and NOAA-flagged values removed | fit the normality table, the Isolation Forest, the learned limits |
| DEV | the six DEV stations, 2020-2021 (`data/real/dev/`) | tuning was allowed here |
| HOLDOUT in time | the same six, 2022-2024 (`data/holdout/real/<STN>_future.csv`) | sealed |
| HOLDOUT in space | eight stations, whole record (`data/holdout/real/<STN>.csv`) | sealed; no threshold was ever chosen by looking at them |

## Extreme-weather windows (chosen by rule, before looking at any verdict)
| Kind | Rule | Window |
|---|---|---|
| low | pressure at least 10 hPa below its trailing 30-day median (cyclones, deep depressions); the 8 deepest per station | +/- 3 days |
| heat | top 0.3 % of daily maximum temperatures; up to 5 per station, 7 days apart | +/- 3 days |
| cold | bottom 0.3 % of daily minimum temperatures; up to 5 per station | +/- 3 days |
| sharp | the largest 3-hour temperature change of each year | +/- 2 days |

The rules and the resulting list are in `data/real/events.json`. Known events that fall out of the rules include Cyclone
Vardah (Chennai, Dec 2016), Fani (Bhubaneswar, May 2019), Amphan (Kolkata, May 2020), Tauktae (Mumbai and Ahmedabad,
May 2021), Michaung (Chennai, Dec 2023), Remal (Kolkata, May 2024) and Biparjoy (Bhuj, Jun 2023).

## Reproduce
```bash
python -m data_tools.isd fetch --years 2016 2024     # ~1 GB into data/raw/isd (git-ignored)
python -m data_tools.isd build                       # one CSV per station
python -m data_tools.make_dataset                    # DEV / HOLDOUT layout + events.json
```
The processed CSVs are committed, so a fresh clone does not need to download anything.

## Known quirks
- Bhubaneswar's reports stop at 08:30 UTC on 3 May 2019, when Fani made landfall: a real outage inside a real event.
- Some station-years have partial coverage (Visakhapatnam 2016 about 70 %, Guwahati 2016-17 about 65 %); gaps are left as gaps.
- Pressure is QNH, which is sea-level-referenced: it tracks weather, not station altitude.
