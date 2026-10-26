#pragma once
#include <stdint.h>
#include <stdbool.h>

void cradle_init(void);
// Block until the cradle is at the next angle. In BUTTON mode the firmware
// owns the counter (expected = next index); in ENCODER mode the absolute index
// is read and must equal `expected`. Returns the trusted angle index, or -1 on
// timeout / wrong position.
int  cradle_wait_angle(uint8_t expected, uint32_t timeout_ms);

void rfsw_init(void);
void rfsw_select(uint8_t port);
