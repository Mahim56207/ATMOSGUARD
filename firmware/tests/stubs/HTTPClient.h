#pragma once
#include "Arduino.h"
struct HTTPClient {
  void begin(const char *) {}
  void addHeader(const char *, const char *) {}
  void setTimeout(uint32_t) {}
  int POST(uint8_t *, size_t) { return 0; }
  void end() {}
};
