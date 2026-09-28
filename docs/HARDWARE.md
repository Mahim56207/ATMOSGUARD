# Hardware node (ESP32 + BME280)

The node is optional for the software to work: `simnode.py` makes the same readings and the same `device_flags`, and every
demo also runs from recorded real data. Use the node when you want a live sensor that reacts to breath, a hair dryer and
hot water.

## Bill of materials (approximate, India, 2026)
| Part | Notes | Rs |
|---|---|---|
| ESP32 DevKit (ESP32-WROOM) | needs a **data** USB cable; many cables are charge-only | 450-700 |
| BME280 breakout (I2C) | 3.3 V version. Address 0x76 or 0x77: read the silkscreen or run an I2C scanner | 250-500 |
| Jumper wires (4), USB power bank or charger | | 100-300 |
| Optional: hair dryer, cup of hot water, small bottle of water | live triggers for temperature up / humidity up | - |

## Wiring
| BME280 | ESP32 |
|---|---|
| VCC | 3V3 (not 5 V) |
| GND | GND |
| SDA | GPIO 21 |
| SCL | GPIO 22 |

## Flash it
1. Arduino IDE: Boards Manager, install **esp32** (Espressif). Libraries: **Adafruit BME280 Library** and **Adafruit Unified Sensor**.
2. `python firmware/node/gen_config.py` writes `firmware/node/config.h` from `config/settings.yaml`, so the node uses the same limits as
   the server. (`--check` exits 1 if it is out of date; a test enforces this.)
3. Copy `firmware/node/secrets.example.h` to `firmware/node/secrets.h`; set the Wi-Fi name and password (**2.4 GHz** - the ESP32 cannot
   join 5 GHz), `API_URL` (your laptop's address, `http://<ip>:8000/ingest`) and `STATION_ID` (must be in `config/stations.yaml`,
   or the API guesses the cadence).
4. Open `firmware/node/node.ino`, pick the board, upload. Serial monitor at 115200 baud.

Expected: "WiFi connected", "clock synced", then one line per minute like `POST 2026-09-28T10:15:00 -> 200`.
Breathe on the sensor: humidity rises and falls back.

## What runs where
| On the ESP32 (`firmware/node/atmos_l0.h`) | On the server |
|---|---|
| 1 Hz sampling, range check per sample, dew point vs temperature, one-minute mean, frozen counter (30 identical minute means), queue of 30 unsent minutes while the network is down | everything else: learned limits, normality, Isolation Forest, timing, fusion, health |

A sample that fails a range check is left out of the minute's mean; what was left out is reported in `device_flags`
(`range:<ch>`, `few_valid:<ch>`, `frozen:<ch>`, `dew_point`). The server records the node's flags as a soft `device` check.

## Breaking the sensor on demand
You do not need buttons on the board. Arm a fault from the dashboard's **Control panel** tab (or `POST /inject`): the node's
next readings are altered on the way in exactly as a failing sensor would alter them (frozen, spike, level shift, drift, noise,
dropout), and the verdict, the reason and the health score react.

## What has and has not been verified
- Verified (in `tests/test_edge_parity.py`): the L0 core, compiled with `g++`, agrees with the Python implementation on 4 000
  dew-point cases and 200 random minutes (including NaN bursts, out-of-range values, dead sensors, frozen runs); the sketch
  type-checks against stand-ins for the Arduino libraries (and the check fails when the sketch is broken on purpose).
- **Not verified:** compilation with the real ESP32 toolchain, running on hardware, Wi-Fi/NTP behaviour, sensor self-heating
  (a BME280 reads slightly warm next to its own electronics; forced mode reduces it), and any energy figure.

## Energy: an estimate, not a measurement
The current sketch keeps Wi-Fi connected and samples at 1 Hz, so it is **not** power-optimised. Typical datasheet values
(Espressif ESP32, Bosch BME280; check your board, regulators and LED add current):

| State | ESP32 (typical) | BME280 |
|---|---|---|
| Wi-Fi connected, idle / modem sleep | roughly 20-70 mA | 3.6 uA at 1 Hz (T+P+RH) |
| Wi-Fi transmitting | peaks of 200 mA and more | |
| Deep sleep | about 10 uA (chip only) | 0.1 uA |

At an average of 50-100 mA the current firmware would run a 2 000 mAh battery for about 20-40 hours. A duty-cycled variant
(wake, read, run L0, transmit, deep-sleep for the rest of the minute) would be orders of magnitude lower, but it is **not
built and not measured here**. To get a real number: put a USB power meter in line and record current in three states (active
send, idle, deep sleep) - that table is the deliverable the build guide asks for (E2).
