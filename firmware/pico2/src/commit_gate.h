#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "record.h"

typedef enum {
    GATE_COMMITTED = 0,
    GATE_REJECTED  = 1,   // comparator withheld the token
    GATE_RING_FULL = 2,
    GATE_FAULT     = 3,   // DMA/PIO state anomaly (should never happen)
} gate_result_t;

typedef struct {
    uint32_t committed, rejected, faults;
} gate_stats_t;

void          gate_init(void);
// `poison` forces view-B grid words to differ from view-A, so lock loss or
// ADC failure is rejected by the same structural path rather than by a
// CPU-side branch around it.
gate_result_t gate_submit(const record_t *staged, bool poison);

// Ring accessors used by the host link (read-only for committed slots).
uint32_t        ring_head(void);           // number of committed slots
const record_t *ring_slot(uint32_t idx);   // idx is a monotonic counter
uint32_t        ring_tail(void);
void            ring_set_tail(uint32_t t);  // host-acknowledged count
const gate_stats_t *gate_stats(void);
