# Demo data

Real recorded events (NOAA ISD airport records, DEV period only). Replay one from the dashboard's Control panel, or `python replay.py data/demo/<file> --speed 3600`.

| file | station | what |
|---|---|---|
| fani_BBI_2019-05.csv | BBI | Cyclone Fani, Bhubaneswar: pressure falls 30 hPa, the station's reports stop at landfall |
| vardah_MAA_2016-12.csv | MAA | Cyclone Vardah, Chennai: pressure falls 32 hPa |
| amphan_CCU_2020-05.csv | CCU | Cyclone Amphan, Kolkata: pressure falls 29 hPa |
| yaas_BBI_2021-05.csv | BBI | Cyclone Yaas, Bhubaneswar |
| outflow_CCU_2021-06.csv | CCU | Thunderstorm outflow, Kolkata: temperature falls up to 14 C in 3 h while humidity jumps. An earlier rule called it a fault |
| outflow_DEL_2021-04.csv | DEL | Outflow, Delhi: humidity jumps 47 % and temperature falls 8 C in an hour. An earlier rule called it a fault |
