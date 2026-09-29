// AtmosGuard L0 on the device: range check, dew point, one-minute mean, frozen counter.
//
// Plain C++11, no Arduino headers, so the SAME code that runs on the ESP32 is compiled and tested on a laptop
// (tests/test_edge_parity.py builds firmware/tests/l0_parity.cpp and compares it with atmos/physics.py and
// simnode.py on thousands of inputs). node.ino only does the I/O around it.
//
// Limits come from config.h (generated from config/settings.yaml), passed in through L0Limits.
#pragma once
#include <math.h>
#include <stdint.h>

namespace atmos {

constexpr int NUM_CHANNELS = 3;
constexpr int CH_TEMPERATURE = 0;
constexpr int CH_PRESSURE = 1;
constexpr int CH_HUMIDITY = 2;

// Magnus constants: the same physical constants as atmos/physics.py
constexpr float MAGNUS_A = 17.62f;
constexpr float MAGNUS_B = 243.12f;

// Flag bits of a finished minute
inline uint16_t flag_range(int ch) { return (uint16_t)(1u << ch); }            // bits 0-2: a sample was outside the L0 range
inline uint16_t flag_few_valid(int ch) { return (uint16_t)(1u << (3 + ch)); }  // bits 3-5: too few valid samples
constexpr uint16_t FLAG_DEW_POINT = (uint16_t)(1u << 6);                        // dew point above air temperature
inline uint16_t flag_frozen(int ch) { return (uint16_t)(1u << (7 + ch)); }     // bits 7-9: same minute mean too many minutes in a row

struct L0Limits {
  float lo[NUM_CHANNELS];
  float hi[NUM_CHANNELS];
  float dew_tolerance;
  uint16_t min_valid;        // fewer valid samples than this in a minute -> channel sent as missing
  uint16_t frozen_minutes;   // this many identical minute means in a row -> frozen flag (0 = check off)
};

// Dew point from temperature (degC) and relative humidity (%). Needs rh > 0.
inline float dew_point_c(float t, float rh) {
  float g = logf(rh / 100.0f) + MAGNUS_A * t / (MAGNUS_B + t);
  return MAGNUS_B * g / (MAGNUS_A - g);
}

// True if the sample is a real number inside the physical range of the channel.
inline bool sample_in_range(const L0Limits &lim, int ch, float v) {
  return !isnan(v) && v >= lim.lo[ch] && v <= lim.hi[ch];
}

struct MinuteState {
  double sum[NUM_CHANNELS];
  uint16_t valid[NUM_CHANNELS];
  uint16_t range_violations[NUM_CHANNELS];
};

inline void minute_reset(MinuteState &m) {
  for (int c = 0; c < NUM_CHANNELS; c++) { m.sum[c] = 0.0; m.valid[c] = 0; m.range_violations[c] = 0; }
}

// One 1 Hz sample. A failed read (NaN) is neither valid nor a range violation.
inline void add_sample(MinuteState &m, const L0Limits &lim, const float v[NUM_CHANNELS]) {
  for (int c = 0; c < NUM_CHANNELS; c++) {
    if (isnan(v[c])) continue;
    if (v[c] < lim.lo[c] || v[c] > lim.hi[c]) { m.range_violations[c]++; continue; }
    m.sum[c] += v[c];
    m.valid[c]++;
  }
}

struct FrozenState {
  float last[NUM_CHANNELS];
  uint16_t run[NUM_CHANNELS];     // how many minutes in a row the mean has been identical (0 = first sighting)
  bool has_last[NUM_CHANNELS];
};

inline void frozen_reset(FrozenState &f) {
  for (int c = 0; c < NUM_CHANNELS; c++) { f.last[c] = 0.0f; f.run[c] = 0; f.has_last[c] = false; }
}

struct MinuteResult {
  bool present[NUM_CHANNELS];
  float value[NUM_CHANNELS];
  uint16_t flags;
};

// Close the minute: mean of the valid samples, the flags, and the frozen counter.
inline MinuteResult finish_minute(const MinuteState &m, const L0Limits &lim, FrozenState &fz) {
  MinuteResult r;
  r.flags = 0;
  for (int c = 0; c < NUM_CHANNELS; c++) {
    r.present[c] = m.valid[c] >= lim.min_valid && m.valid[c] > 0;
    r.value[c] = r.present[c] ? (float)(m.sum[c] / m.valid[c]) : 0.0f;
    if (!r.present[c]) r.flags |= flag_few_valid(c);
    if (m.range_violations[c] > 0) r.flags |= flag_range(c);
    // frozen counter: identical mean minute after minute. A missing minute breaks the run.
    if (!r.present[c]) {
      fz.has_last[c] = false;
      fz.run[c] = 0;
    } else {
      if (fz.has_last[c] && r.value[c] == fz.last[c]) fz.run[c]++;
      else fz.run[c] = 0;
      fz.last[c] = r.value[c];
      fz.has_last[c] = true;
      if (lim.frozen_minutes > 0 && (uint32_t)fz.run[c] + 1u >= lim.frozen_minutes) r.flags |= flag_frozen(c);
    }
  }
  if (r.present[CH_TEMPERATURE] && r.present[CH_HUMIDITY] && r.value[CH_HUMIDITY] > 0.0f &&
      dew_point_c(r.value[CH_TEMPERATURE], r.value[CH_HUMIDITY]) > r.value[CH_TEMPERATURE] + lim.dew_tolerance) {
    r.flags |= FLAG_DEW_POINT;
  }
  return r;
}

}  // namespace atmos
