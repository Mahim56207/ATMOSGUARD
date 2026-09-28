// AtmosGuard node: ESP32 + BME280.
//
//  * reads the sensor at 1 Hz (SAMPLE_INTERVAL_MS)
//  * runs the L0 physics checks on every sample, on the device (limits come from config.h)
//  * every AGGREGATE_SECONDS (1 minute) sends the mean of the valid samples to the API by HTTP POST /ingest
//  * keeps unsent minutes in a small queue while the network is down
//
// Needed: ESP32 board package, library "Adafruit BME280" (and its "Adafruit Unified Sensor").
// Setup:  python firmware/node/gen_config.py   -> config.h   (same limits as the server)
//         copy secrets.example.h to secrets.h and fill it in
// Wiring: BME280 on I2C. SDA = GPIO 21, SCL = GPIO 22 (ESP32 default). I2C address 0x76 (0x77 on some boards).
//
// Honesty notes:
//  * A sample that fails a check or reads NaN is left out of the minute's mean. Only the 1-minute mean leaves
//    the device, so the individual 1 Hz samples are not kept. What was left out is reported in `device_flags`.
//  * Timestamps are UTC from NTP, written without a zone, like the CSV files. No report is made until the
//    clock is synced.
//  * If the queue is full, the OLDEST unsent minute is dropped (printed on Serial).

#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Adafruit_BME280.h>
#include <math.h>
#include <time.h>
#include "config.h"
#include "secrets.h"

#define BME_ADDRESS 0x76
#define NUM_CHANNELS 3
#define CH_TEMPERATURE 0
#define CH_PRESSURE 1
#define CH_HUMIDITY 2
#define MIN_VALID_YEAR 2024          // an unsynced ESP32 clock says 1970
#define WIFI_RETRY_MS 10000UL
#define WIFI_CONNECT_WAIT_MS 20000UL
#define NTP_WAIT_MS 20000UL
#define MAGNUS_A 17.62f
#define MAGNUS_B 243.12f

static const char *CHANNEL_NAMES[NUM_CHANNELS] = {"temperature_c", "pressure_hpa", "humidity_pct"};
static const float RANGE_MIN[NUM_CHANNELS] = {L0_TEMPERATURE_MIN_C, L0_PRESSURE_MIN_HPA, L0_HUMIDITY_MIN_PCT};
static const float RANGE_MAX[NUM_CHANNELS] = {L0_TEMPERATURE_MAX_C, L0_PRESSURE_MAX_HPA, L0_HUMIDITY_MAX_PCT};

// device flag bits (names sent to the API are built from these in flagNames())
#define FLAG_RANGE(ch) (1u << (ch))              // bits 0-2: a sample of this channel was outside the L0 range
#define FLAG_FEW_VALID(ch) (1u << (3 + (ch)))    // bits 3-5: too few valid samples, channel sent as missing
#define FLAG_DEW_POINT (1u << 6)                 // dew point above air temperature

struct Report {
  char timestamp[20];                            // "2026-01-01T12:00:00"
  float value[NUM_CHANNELS];
  bool present[NUM_CHANNELS];
  uint8_t flags;
};

Adafruit_BME280 bme;
Report queue[BUFFER_SLOTS];
int queueHead = 0;
int queueCount = 0;

// state of the minute being collected
double sum[NUM_CHANNELS];
uint16_t validCount[NUM_CHANNELS];
uint16_t rangeViolations[NUM_CHANNELS];
uint16_t ticks = 0;
uint32_t nextSampleAt = 0;
uint32_t lastWifiTry = 0;
bool bmeOk = false;

// ------------------------------------------------------------------------------------------------
bool clockSynced() {
  time_t now = time(nullptr);
  struct tm t;
  gmtime_r(&now, &t);
  return (t.tm_year + 1900) >= MIN_VALID_YEAR;
}

void formatNow(char *out, size_t size) {
  time_t now = time(nullptr);
  struct tm t;
  gmtime_r(&now, &t);
  strftime(out, size, "%Y-%m-%dT%H:%M:%S", &t);
}

float dewPointC(float t, float rh) {
  float g = logf(rh / 100.0f) + MAGNUS_A * t / (MAGNUS_B + t);
  return MAGNUS_B * g / (MAGNUS_A - g);
}

void resetMinute() {
  for (int c = 0; c < NUM_CHANNELS; c++) {
    sum[c] = 0.0;
    validCount[c] = 0;
    rangeViolations[c] = 0;
  }
  ticks = 0;
}

void connectWifi(uint32_t waitMs) {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < waitMs) {
    delay(250);
  }
  lastWifiTry = millis();
  Serial.println(WiFi.status() == WL_CONNECTED ? "WiFi connected" : "WiFi not connected");
}

// ------------------------------------------------------------------------------------------------
// One sample: read, run the L0 range check on each channel, add the valid ones to the minute's sums.
void takeSample() {
  float v[NUM_CHANNELS];
  v[CH_TEMPERATURE] = bme.readTemperature();
  v[CH_PRESSURE] = bme.readPressure() / 100.0f;      // Pa -> hPa
  v[CH_HUMIDITY] = bme.readHumidity();
  for (int c = 0; c < NUM_CHANNELS; c++) {
    if (isnan(v[c])) continue;                       // failed read: not valid, not a range violation
    if (v[c] < RANGE_MIN[c] || v[c] > RANGE_MAX[c]) {
      rangeViolations[c]++;
      continue;
    }
    sum[c] += v[c];
    validCount[c]++;
  }
  ticks++;
}

// Close the minute: build a Report from the sums and put it in the queue.
void finishMinute() {
  Report r;
  formatNow(r.timestamp, sizeof(r.timestamp));
  r.flags = 0;
  for (int c = 0; c < NUM_CHANNELS; c++) {
    r.present[c] = validCount[c] >= MIN_VALID_SAMPLES;
    r.value[c] = r.present[c] ? (float)(sum[c] / validCount[c]) : 0.0f;
    if (!r.present[c]) r.flags |= FLAG_FEW_VALID(c);
    if (rangeViolations[c] > 0) r.flags |= FLAG_RANGE(c);
  }
  if (r.present[CH_TEMPERATURE] && r.present[CH_HUMIDITY] && r.value[CH_HUMIDITY] > 0.0f &&
      dewPointC(r.value[CH_TEMPERATURE], r.value[CH_HUMIDITY]) > r.value[CH_TEMPERATURE] + L0_DEW_POINT_TOLERANCE_C) {
    r.flags |= FLAG_DEW_POINT;
  }
  if (queueCount == BUFFER_SLOTS) {                  // full: drop the oldest unsent minute
    Serial.println("queue full: dropping the oldest unsent minute");
    queueHead = (queueHead + 1) % BUFFER_SLOTS;
    queueCount--;
  }
  queue[(queueHead + queueCount) % BUFFER_SLOTS] = r;
  queueCount++;
  resetMinute();
}

// ------------------------------------------------------------------------------------------------
// Build the JSON body. Missing values are sent as null so the server sees a dropout.
int buildJson(const Report &r, char *out, size_t size) {
  char field[NUM_CHANNELS][20];
  for (int c = 0; c < NUM_CHANNELS; c++) {
    if (r.present[c]) snprintf(field[c], sizeof(field[c]), "%.3f", r.value[c]);
    else snprintf(field[c], sizeof(field[c]), "null");
  }
  char flags[200];
  size_t n = 0;
  flags[0] = '\0';
  bool first = true;
  for (int c = 0; c < NUM_CHANNELS; c++) {
    if (r.flags & FLAG_RANGE(c)) {
      n += snprintf(flags + n, sizeof(flags) - n, "%s\"range:%s\"", first ? "" : ",", CHANNEL_NAMES[c]);
      first = false;
    }
    if (r.flags & FLAG_FEW_VALID(c)) {
      n += snprintf(flags + n, sizeof(flags) - n, "%s\"few_valid:%s\"", first ? "" : ",", CHANNEL_NAMES[c]);
      first = false;
    }
  }
  if (r.flags & FLAG_DEW_POINT) {
    n += snprintf(flags + n, sizeof(flags) - n, "%s\"dew_point\"", first ? "" : ",");
  }
  return snprintf(out, size,
                  "{\"station_id\":\"%s\",\"timestamp\":\"%s\",\"temperature_c\":%s,\"pressure_hpa\":%s,"
                  "\"humidity_pct\":%s,\"device_flags\":[%s]}",
                  STATION_ID, r.timestamp, field[CH_TEMPERATURE], field[CH_PRESSURE], field[CH_HUMIDITY], flags);
}

bool postReport(const Report &r) {
  char body[420];
  buildJson(r, body, sizeof(body));
  HTTPClient http;
  http.begin(API_URL);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(POST_TIMEOUT_MS);
  int code = http.POST((uint8_t *)body, strlen(body));
  http.end();
  Serial.printf("POST %s -> %d\n", r.timestamp, code);
  return code >= 200 && code < 300;
}

// Send the oldest first. Stop at the first failure and try again next minute.
void flushQueue() {
  while (queueCount > 0 && WiFi.status() == WL_CONNECTED) {
    if (!postReport(queue[queueHead])) return;
    queueHead = (queueHead + 1) % BUFFER_SLOTS;
    queueCount--;
  }
}

// ------------------------------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  Wire.begin();
  bmeOk = bme.begin(BME_ADDRESS);
  if (!bmeOk) Serial.println("BME280 not found: check wiring and the I2C address");
  connectWifi(WIFI_CONNECT_WAIT_MS);
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");   // UTC
  uint32_t start = millis();
  while (!clockSynced() && millis() - start < NTP_WAIT_MS) delay(250);
  Serial.println(clockSynced() ? "clock synced" : "clock not synced yet: no reports until it is");
  resetMinute();
  nextSampleAt = millis();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED && millis() - lastWifiTry > WIFI_RETRY_MS) connectWifi(WIFI_RETRY_MS / 2);
  if ((int32_t)(millis() - nextSampleAt) < 0) return;
  nextSampleAt += SAMPLE_INTERVAL_MS;
  if (!clockSynced()) { resetMinute(); return; }       // nothing is reported without a real clock
  if (bmeOk) takeSample(); else ticks++;               // a dead sensor still closes the minute (all channels missing)
  if (ticks * (SAMPLE_INTERVAL_MS / 1000UL) >= AGGREGATE_SECONDS) {
    finishMinute();
    flushQueue();
  }
}
