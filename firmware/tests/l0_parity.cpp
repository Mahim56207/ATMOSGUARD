// Host build of the device's L0 core (firmware/node/atmos_l0.h), driven from stdin by tests/test_edge_parity.py.
//   R                       reset the frozen counter
//   D t rh                  print the dew point
//   M n                     followed by n lines "t p rh" (nan allowed): close the minute and print
//                           "<present x3> <value x3> <flags>"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include "config.h"
#include "atmos_l0.h"

static const atmos::L0Limits LIMITS = {
  {L0_TEMPERATURE_MIN_C, L0_PRESSURE_MIN_HPA, L0_HUMIDITY_MIN_PCT},
  {L0_TEMPERATURE_MAX_C, L0_PRESSURE_MAX_HPA, L0_HUMIDITY_MAX_PCT},
  L0_DEW_POINT_TOLERANCE_C, MIN_VALID_SAMPLES, L0_FROZEN_MINUTES};

int main() {
  atmos::FrozenState fz;
  atmos::frozen_reset(fz);
  char cmd[8];
  while (scanf("%7s", cmd) == 1) {
    if (!strcmp(cmd, "R")) {
      atmos::frozen_reset(fz);
    } else if (!strcmp(cmd, "D")) {
      float t, rh;
      if (scanf("%f %f", &t, &rh) != 2) return 2;
      printf("%.6f\n", atmos::dew_point_c(t, rh));
    } else if (!strcmp(cmd, "M")) {
      int n;
      if (scanf("%d", &n) != 1) return 2;
      atmos::MinuteState m;
      atmos::minute_reset(m);
      for (int i = 0; i < n; i++) {
        float v[3];
        if (scanf("%f %f %f", &v[0], &v[1], &v[2]) != 3) return 2;
        atmos::add_sample(m, LIMITS, v);
      }
      atmos::MinuteResult r = atmos::finish_minute(m, LIMITS, fz);
      printf("%d %d %d %.6f %.6f %.6f %u\n", r.present[0], r.present[1], r.present[2], r.value[0], r.value[1],
             r.value[2], (unsigned)r.flags);
    }
  }
  return 0;
}
