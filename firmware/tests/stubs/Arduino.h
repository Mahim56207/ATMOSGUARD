// Minimal stand-ins for the Arduino-ESP32 core, ONLY so firmware/node/node.ino can be type-checked with g++ on a
// laptop (tests/test_edge_parity.py). They do nothing. This is not a simulator of the hardware.
#pragma once
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

inline uint32_t millis() { return 0; }
inline void delay(uint32_t) {}
inline void configTime(long, int, const char *, const char * = nullptr) {}

struct SerialStub {
  void begin(unsigned long) {}
  template <typename T> void println(const T &) {}
  void printf(const char *, ...) __attribute__((format(printf, 2, 3))) {}
};
static SerialStub Serial;
