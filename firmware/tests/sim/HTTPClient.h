#pragma once
#include "Arduino.h"
struct HTTPClient {
  const char *url = "";
  void begin(const char *u) { url = u; }
  void addHeader(const char *k, const char *v) { printf("HEADER %s: %s\n", k, v); }
  void setTimeout(uint32_t) {}
  int POST(uint8_t *body, size_t n) {
    if (sim_http_code < 200 || sim_http_code >= 300) return sim_http_code;      // not delivered: nothing reaches the server
    printf("POST_BODY %.*s\n", (int)n, (const char *)body);
    return sim_http_code;
  }
  void end() {}
};
