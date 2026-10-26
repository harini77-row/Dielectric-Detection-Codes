#include "cradle.h"
#include "config.h"
#include "pico/stdlib.h"

void cradle_init(void) {
#if CRADLE_MODE == CRADLE_MODE_BUTTON
    gpio_init(CRADLE_PIN_BUTTON);
    gpio_set_dir(CRADLE_PIN_BUTTON, GPIO_IN);
    gpio_pull_up(CRADLE_PIN_BUTTON);              // button to GND
#else
    for (int i = 0; i < 4; i++) {
        gpio_init(CRADLE_PIN_ENC0 + i);
        gpio_set_dir(CRADLE_PIN_ENC0 + i, GPIO_IN);
        gpio_pull_up(CRADLE_PIN_ENC0 + i);
    }
#endif
}

#if CRADLE_MODE == CRADLE_MODE_ENCODER
static uint8_t enc_read(void) {
    return (uint8_t)((gpio_get_all() >> CRADLE_PIN_ENC0) & 0xFu);
}
#endif

int cradle_wait_angle(uint8_t expected, uint32_t timeout_ms) {
    absolute_time_t dl = make_timeout_time_ms(timeout_ms);
#if CRADLE_MODE == CRADLE_MODE_BUTTON
    // wait for release, then a press held >= 30 ms, then release
    while (!gpio_get(CRADLE_PIN_BUTTON)) if (time_reached(dl)) return -1;
    for (;;) {
        if (time_reached(dl)) return -1;
        if (!gpio_get(CRADLE_PIN_BUTTON)) {
            sleep_ms(30);
            if (!gpio_get(CRADLE_PIN_BUTTON)) break;
        }
    }
    while (!gpio_get(CRADLE_PIN_BUTTON)) if (time_reached(dl)) return -1;
    sleep_ms(200);              // let the detent settle mechanically
    return expected;
#else
    for (;;) {
        if (time_reached(dl)) return -1;
        uint8_t a = enc_read();
        sleep_ms(50);
        uint8_t b = enc_read();
        if (a == b && a == expected) { sleep_ms(200); return a; }
    }
#endif
}

void rfsw_init(void) {
    gpio_init(SW_PIN_V1); gpio_set_dir(SW_PIN_V1, GPIO_OUT);
    gpio_init(SW_PIN_V2); gpio_set_dir(SW_PIN_V2, GPIO_OUT);
    rfsw_select(0);
}

void rfsw_select(uint8_t port) {
    gpio_put(SW_PIN_V1, port & 1u);
    gpio_put(SW_PIN_V2, (port >> 1) & 1u);
    busy_wait_us_32(5);
}
