#pragma once
#include "Arduino.h"
#define WL_CONNECTED 3
#define WIFI_STA 1
struct WiFiSim {
  void mode(int) {}
  void begin(const char *, const char *) {}
  void disconnect() {}
  int status() { return sim_wifi_up ? WL_CONNECTED : 0; }
};
static WiFiSim WiFi;
