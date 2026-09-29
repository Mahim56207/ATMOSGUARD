# Hardware test log (fill this in when you flash the node)

Everything the software can prove without the chip is proved (`docs/HARDWARE.md`, "What has and has not been verified"). What remains is measurement. This page
is the shortest path to it: about one hour with a board, a BME280 and a laptop. Write the results here and commit them, so a judge can see they are yours.

## 1. Flash (10 minutes)
Follow `docs/HARDWARE.md` "Flash it". Success is the serial monitor printing `WiFi connected`, `clock synced`, then `POST <time> -> 200` once a minute.

| Check | Expected | Your result |
|---|---|---|
| Compiles with the real ESP32 toolchain | no errors (warnings are worth writing down) | |
| Board and toolchain versions | write them down | |
| `WiFi connected` and `clock synced` within 40 s | yes | |
| One `POST ... -> 200` per minute for 10 minutes | yes | |
| The reading appears in the dashboard's Live monitor | yes | |

## 2. Break it on purpose (15 minutes)
| Action | Expected | Your result |
|---|---|---|
| Breathe on the sensor | humidity rises and falls back; verdict stays `VALID` or a soft flag | |
| Hair dryer for 20 s, then remove | temperature rises and falls; not a `FAULT` (a smooth change on one channel with the others quiet may be `SUSPECT`) | |
| Unplug SDA | readings become `null`, `few_valid:*` flags, the server calls it a `FAULT` (dropout) | |
| Turn the Wi-Fi router off for 5 minutes, then on | no minute is lost; they arrive in order with their own timestamps | |
| Leave the sensor untouched for 45 minutes in a still room | `frozen:*` may appear only if the mean repeats exactly; note what it does (a BME280 usually jitters in the last digit) | |

## 3. Numbers to measure (30 minutes)
| Quantity | How | Result |
|---|---|---|
| Current draw, Wi-Fi connected, sampling at 1 Hz | USB power meter or a multimeter in series, 5 minutes, average | |
| Sensor offset against a reference thermometer | put both in a still room for 30 minutes; write the difference | |
| Time from power-on to the first POST | serial monitor timestamps | |
| Free heap after 1 hour (`ESP.getFreeHeap()` added to the serial print) | to check for a leak | |

## 4. What to say about it
Say "the sketch was compiled with <toolchain, version> and ran for <hours> on <board>", and quote the table above. Do not quote an energy figure that is not in the table.
