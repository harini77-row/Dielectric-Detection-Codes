#include "ads1115.h"
#include "config.h"
#include "pico/stdlib.h"
#include "hardware/i2c.h"

#define REG_CONV 0x00
#define REG_CFG  0x01

static bool wr16(uint8_t reg, uint16_t v) {
    uint8_t b[3] = { reg, (uint8_t)(v >> 8), (uint8_t)v };
    return i2c_write_timeout_us(ADS_I2C, ADS_ADDR, b, 3, false, 2000) == 3;
}
static bool rd16(uint8_t reg, uint16_t *v) {
    uint8_t b[2];
    if (i2c_write_timeout_us(ADS_I2C, ADS_ADDR, &reg, 1, true, 2000) != 1) return false;
    if (i2c_read_timeout_us(ADS_I2C, ADS_ADDR, b, 2, false, 2000) != 2) return false;
    *v = ((uint16_t)b[0] << 8) | b[1];
    return true;
}

bool ads1115_init(void) {
    i2c_init(ADS_I2C, 400000);
    gpio_set_function(ADS_PIN_SDA, GPIO_FUNC_I2C);
    gpio_set_function(ADS_PIN_SCL, GPIO_FUNC_I2C);
    gpio_pull_up(ADS_PIN_SDA);
    gpio_pull_up(ADS_PIN_SCL);
    uint16_t v;
    return rd16(REG_CFG, &v);
}

bool ads1115_read(uint8_t ch, int16_t *code) {
    uint16_t cfg = (1u << 15)                     // OS: start
                 | ((uint16_t)(4u + (ch & 3u)) << 12) // MUX: AINx vs GND
                 | (2u << 9)                      // PGA +-2.048 V
                 | (1u << 8)                      // single-shot
                 | (7u << 5)                      // 860 SPS
                 | 3u;                            // comparator off
    if (!wr16(REG_CFG, cfg)) return false;
    absolute_time_t dl = make_timeout_time_us(5000);
    uint16_t s;
    busy_wait_us_32(1000);
    do {
        if (!rd16(REG_CFG, &s)) return false;
        if (time_reached(dl)) return false;
    } while (!(s & 0x8000));
    uint16_t raw;
    if (!rd16(REG_CONV, &raw)) return false;
    *code = (int16_t)raw;
    return true;
}

bool ads1115_read_avg(uint8_t ch, uint16_t n, int16_t *code) {
    int32_t acc = 0;
    for (uint16_t i = 0; i < n; i++) {
        int16_t c;
        if (!ads1115_read(ch, &c)) return false;
        acc += c;
    }
    *code = (int16_t)((acc + (int32_t)(n / 2)) / (int32_t)n);
    return true;
}
