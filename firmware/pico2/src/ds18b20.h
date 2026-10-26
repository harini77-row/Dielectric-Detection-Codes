#pragma once
#include <stdint.h>
#include <stdbool.h>

void ds18b20_init(void);
// Blocking 12-bit conversion (~750 ms). temp_c16 = degC * 16.
bool ds18b20_read(int16_t *temp_c16);
