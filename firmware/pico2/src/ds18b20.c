// Bit-banged 1-Wire for a single DS18B20 on the cradle (TO-92, outside the
// RF exclusion zone). External 4.7k pull-up to 3V3 required.
#include "ds18b20.h"
#include "config.h"
#include "pico/stdlib.h"
#include "hardware/sync.h"

static inline void bus_low(void)     { gpio_set_dir(DS_PIN, GPIO_OUT); gpio_put(DS_PIN, 0); }
static inline void bus_release(void) { gpio_set_dir(DS_PIN, GPIO_IN); }

static bool ow_reset(void) {
    uint32_t s = save_and_disable_interrupts();
    bus_low();      busy_wait_us_32(480);
    bus_release();  busy_wait_us_32(70);
    bool present = !gpio_get(DS_PIN);
    restore_interrupts(s);
    busy_wait_us_32(410);
    return present;
}

static void ow_write_bit(int b) {
    uint32_t s = save_and_disable_interrupts();
    bus_low();
    busy_wait_us_32(b ? 6 : 60);
    bus_release();
    busy_wait_us_32(b ? 64 : 10);
    restore_interrupts(s);
}

static int ow_read_bit(void) {
    uint32_t s = save_and_disable_interrupts();
    bus_low();      busy_wait_us_32(6);
    bus_release();  busy_wait_us_32(9);
    int b = gpio_get(DS_PIN);
    restore_interrupts(s);
    busy_wait_us_32(55);
    return b;
}

static void ow_write(uint8_t v) { for (int i = 0; i < 8; i++) ow_write_bit((v >> i) & 1); }
static uint8_t ow_read(void) {
    uint8_t v = 0;
    for (int i = 0; i < 8; i++) v |= (uint8_t)(ow_read_bit() << i);
    return v;
}

static uint8_t crc8_maxim(const uint8_t *d, int n) {
    uint8_t crc = 0;
    while (n--) {
        uint8_t in = *d++;
        for (int i = 0; i < 8; i++) {
            uint8_t mix = (crc ^ in) & 1u;
            crc >>= 1;
            if (mix) crc ^= 0x8C;
            in >>= 1;
        }
    }
    return crc;
}

void ds18b20_init(void) {
    gpio_init(DS_PIN);
    gpio_put(DS_PIN, 0);
    bus_release();
}

bool ds18b20_read(int16_t *t) {
    if (!ow_reset()) return false;
    ow_write(0xCC);             // SKIP ROM (single sensor)
    ow_write(0x44);             // CONVERT T
    absolute_time_t dl = make_timeout_time_ms(900);
    while (!ow_read_bit())
        if (time_reached(dl)) return false;
    if (!ow_reset()) return false;
    ow_write(0xCC);
    ow_write(0xBE);             // READ SCRATCHPAD
    uint8_t sp[9];
    for (int i = 0; i < 9; i++) sp[i] = ow_read();
    if (crc8_maxim(sp, 8) != sp[8]) return false;
    *t = (int16_t)((uint16_t)sp[1] << 8 | sp[0]);
    return true;
}
