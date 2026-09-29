#pragma once
#include "Arduino.h"
struct Adafruit_BME280 {
  bool begin(uint8_t) { return false; }
  float readTemperature() { return NAN; }
  float readPressure() { return NAN; }
  float readHumidity() { return NAN; }
};
