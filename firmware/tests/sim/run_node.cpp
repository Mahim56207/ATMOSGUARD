// Runs firmware/node/node.ino on the laptop for a scripted number of virtual minutes and prints what it POSTs.
//   run_node <scenario> <minutes>
// scenarios: clean, stuck, out_of_range, dead, outage, long_outage, unsynced, no_sensor
// Every second the script sets the sensor values, then calls loop() (the sketch's own timing decides what happens).
#include "Arduino.h"
uint32_t sim_millis = 0;
time_t sim_epoch0 = 1767268800;         // 2026-01-01T12:00:00Z
bool sim_wifi_up = true;
int sim_http_code = 200;
float sim_value[3] = {21.5f, 1004.0f, 55.0f};
bool sim_sensor_present = true;

#include "node.ino"

int main(int argc, char **argv) {
  const char *scenario = argc > 1 ? argv[1] : "clean";
  int minutes = argc > 2 ? atoi(argv[2]) : 10;
  if (!strcmp(scenario, "unsynced")) sim_epoch0 = 0;
  if (!strcmp(scenario, "no_sensor")) sim_sensor_present = false;
  setup();
  uint32_t end = sim_millis + (uint32_t)minutes * 60000UL;
  unsigned n = 0;
  while (sim_millis < end) {
    unsigned second = n / 10;                      // loop() is called 10 times a second of virtual time
    unsigned minute = second / 60;
    float wob = 0.05f * (float)((second * 7) % 11) / 11.0f;
    sim_value[0] = 21.5f + 0.4f * sinf((float)minute / 9.0f) + wob;
    sim_value[1] = 1004.0f + 0.3f * sinf((float)minute / 40.0f) + wob * 0.5f;
    sim_value[2] = 55.0f + 3.0f * sinf((float)minute / 15.0f) + wob * 4.0f;
    if (!strcmp(scenario, "stuck")) { sim_value[0] = 21.5f; }                     // temperature repeats exactly
    if (!strcmp(scenario, "out_of_range") && minute >= 2) sim_value[1] = 1250.0f;
    if (!strcmp(scenario, "dead")) { sim_value[0] = sim_value[1] = sim_value[2] = NAN; }
    if (!strcmp(scenario, "outage") || !strcmp(scenario, "long_outage")) {
      bool down = !strcmp(scenario, "outage") ? (minute >= 2 && minute < 6) : (minute >= 1 && minute < 40);
      sim_wifi_up = !down;
      sim_http_code = down ? 0 : 200;
    }
    loop();
    sim_millis += 100;
    n++;
  }
  return 0;
}
