#pragma once
#include "Arduino.h"
struct Adafruit_BME280 {
  bool begin(uint8_t) { return sim_sensor_present; }
  float readTemperature() { return sim_value[0]; }
  float readPressure() { return sim_value[1] * 100.0f; }       // the real library returns Pa
  float readHumidity() { return sim_value[2]; }
};
