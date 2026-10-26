#pragma once
#include <stdint.h>
#include <stdbool.h>

typedef struct {
    uint32_t reg[6];
    uint32_t int_n, frac, mod;
    uint32_t rf_div;
    uint64_t actual_hz;     // what the programmed registers actually produce
} adf4351_plan_t;

void adf4351_init(void);
// Compute registers for f_hz (pure function, unit-testable on host).
bool adf4351_compute(uint64_t f_hz, adf4351_plan_t *out);
// Program and wait for lock. Returns true if LD asserted before timeout.
bool adf4351_tune(uint64_t f_hz, adf4351_plan_t *out);
bool adf4351_locked(void);
void adf4351_rf_enable(bool on);
