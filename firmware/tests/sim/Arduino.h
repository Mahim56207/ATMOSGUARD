// A host SIMULATOR of the Arduino-ESP32 pieces node.ino uses: a virtual clock (millis, delay, time), a scripted BME280, WiFi that can
// go down, and an HTTP client that records every POST body. It lets node.ino run for real on a laptop, minute by minute, and lets a test
// feed what the sketch would have sent to the real API. It is NOT the ESP32: no RTOS, no I2C bus, no radio, no 32-bit timer roll-over
// beyond the plain uint32_t arithmetic the sketch itself does. (The type-check-only stand-ins live in ../stubs.)
#pragma once
#include <math.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

extern uint32_t sim_millis;             // virtual milliseconds since boot
extern time_t sim_epoch0;               // virtual UTC at boot (0 = the clock is not synced)
extern bool sim_wifi_up;
extern int sim_http_code;               // what the server answers (0 = unreachable)
extern float sim_value[3];              // what the sensor reads now: temperature C, pressure hPa, humidity %
extern bool sim_sensor_present;

inline uint32_t millis() { return sim_millis; }
inline void delay(uint32_t ms) { sim_millis += ms; }
inline time_t sim_time(time_t *out) {
  time_t now = sim_epoch0 == 0 ? (time_t)(sim_millis / 1000) : sim_epoch0 + (time_t)(sim_millis / 1000);
  if (out) *out = now;
  return now;
}
#define time(x) sim_time(x)
inline void configTime(long, int, const char *, const char * = nullptr) {}

struct SerialSim {
  void begin(unsigned long) {}
  void println(const char *s) { ::printf("SERIAL %s\n", s); }
  void printf(const char *fmt, ...) __attribute__((format(printf, 2, 3))) {
    va_list a; va_start(a, fmt);
    char buf[256]; vsnprintf(buf, sizeof(buf), fmt, a); va_end(a);
    ::printf("SERIAL %s", buf);
  }
};
static SerialSim Serial;
