#pragma once
#include <stdint.h>
#include <stdbool.h>

bool ads1115_init(void);
// Single-shot, +-2.048 V, 860 SPS. Returns false on I2C error/timeout.
bool ads1115_read(uint8_t ch, int16_t *code);
// Average n conversions (integer mean, rounded).
bool ads1115_read_avg(uint8_t ch, uint16_t n, int16_t *code);
