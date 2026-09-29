#pragma once
#include "Arduino.h"
struct WireStub { void begin() {} };
static WireStub Wire;
