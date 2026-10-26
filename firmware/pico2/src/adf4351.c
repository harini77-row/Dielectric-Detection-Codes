// ADF4351 fractional-N synthesiser driver.
// A free-running VCO cannot substitute here: the enrolment baseline depends on
// frequency repeatability across weeks, which only a reference-locked PLL gives.
#include "adf4351.h"
#include "config.h"

#ifndef PGDD_HOST_TEST
#include "pico/stdlib.h"
#include "hardware/spi.h"
#endif

#define PFD_HZ      ((uint64_t)ADF_REF_HZ)        // R=1, no doubler, no /2
#define VCO_MIN_HZ  2200000000ull
#define VCO_MAX_HZ  4400000000ull

static bool rf_on = true;

bool adf4351_compute(uint64_t f_hz, adf4351_plan_t *p) {
    if (f_hz < 35000000ull || f_hz > 4400000000ull) return false;

    uint32_t div = 1, div_sel = 0;
    while (f_hz * div < VCO_MIN_HZ && div < 64) { div <<= 1; div_sel++; }
    uint64_t vco = f_hz * div;
    if (vco > VCO_MAX_HZ) return false;

    uint32_t mod = (uint32_t)(PFD_HZ / ADF_CHAN_SPACING_HZ);   // 250
    if (mod < 2 || mod > 4095) return false;
    uint32_t int_n = (uint32_t)(vco / PFD_HZ);
    uint64_t rem   = vco % PFD_HZ;
    uint32_t frac  = (uint32_t)((rem * mod + PFD_HZ / 2) / PFD_HZ);
    if (frac >= mod) { int_n++; frac = 0; }

    // prescaler: 8/9 mandatory above 3.6 GHz VCO; needs INT >= 75
    uint32_t prescaler = (vco > 3600000000ull || int_n >= 75) ? 1u : 0u;
    if (prescaler ? int_n < 75 : int_n < 23) return false;
    if (int_n > 65535) return false;

    uint32_t bs_div = (uint32_t)((PFD_HZ + 124999) / 125000);   // fPFD/BS <= 125 kHz
    if (bs_div > 255) bs_div = 255;

    // R0: INT[30:15] FRAC[14:3]
    p->reg[0] = (int_n << 15) | (frac << 3) | 0u;
    // R1: prescaler[27] phase=1[26:15] MOD[14:3]
    p->reg[1] = (prescaler << 27) | (1u << 15) | (mod << 3) | 1u;
    // R2: MUXOUT=110 dig. LD, R=1, CP=0111 (2.5 mA), LDF=0 (frac-N), LDP=0,
    //     PD polarity positive
    p->reg[2] = (6u << 26) | (1u << 14) | (7u << 9) | (1u << 6) | 2u;
    // R3: clock divider 150, ABP=0 (frac-N)
    p->reg[3] = (150u << 3) | 3u;
    // R4: feedback=fundamental, RF div, band-select div, MTLD (mute till lock),
    //     RF out enable, output power
    p->reg[4] = (1u << 23) | (div_sel << 20) | (bs_div << 12) | (1u << 10) |
                ((rf_on ? 1u : 0u) << 5) | ((uint32_t)ADF_OUT_POWER << 3) | 4u;
    // R5: LD pin = digital lock detect
    p->reg[5] = (1u << 22) | (3u << 19) | 5u;

    p->int_n = int_n; p->frac = frac; p->mod = mod; p->rf_div = div;
    // actual = PFD*(INT + FRAC/MOD)/div, exact integer arithmetic
    p->actual_hz = (PFD_HZ * ((uint64_t)int_n * mod + frac) / mod) / div;
    return true;
}

#ifndef PGDD_HOST_TEST
static void write_reg(uint32_t v) {
    uint8_t b[4] = { (uint8_t)(v >> 24), (uint8_t)(v >> 16), (uint8_t)(v >> 8), (uint8_t)v };
    gpio_put(ADF_PIN_LE, 0);
    spi_write_blocking(ADF_SPI, b, 4);
    gpio_put(ADF_PIN_LE, 1);           // data latched on LE rising edge
    busy_wait_us_32(1);
    gpio_put(ADF_PIN_LE, 0);
}

void adf4351_init(void) {
    spi_init(ADF_SPI, 4000000);
    spi_set_format(ADF_SPI, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);
    gpio_set_function(ADF_PIN_SCK, GPIO_FUNC_SPI);
    gpio_set_function(ADF_PIN_MOSI, GPIO_FUNC_SPI);
    gpio_init(ADF_PIN_LE); gpio_set_dir(ADF_PIN_LE, GPIO_OUT); gpio_put(ADF_PIN_LE, 0);
    gpio_init(ADF_PIN_CE); gpio_set_dir(ADF_PIN_CE, GPIO_OUT); gpio_put(ADF_PIN_CE, 1);
    gpio_init(ADF_PIN_LD); gpio_set_dir(ADF_PIN_LD, GPIO_IN);  gpio_pull_down(ADF_PIN_LD);
    sleep_ms(5);
}

bool adf4351_locked(void) { return gpio_get(ADF_PIN_LD); }

bool adf4351_tune(uint64_t f_hz, adf4351_plan_t *p) {
    if (!adf4351_compute(f_hz, p)) return false;
    for (int i = 5; i >= 0; i--) write_reg(p->reg[i]);   // R0 last triggers update
    absolute_time_t dl = make_timeout_time_us(ADF_LOCK_TIMEOUT_US);
    busy_wait_us_32(50);
    while (!adf4351_locked())
        if (time_reached(dl)) return false;
    return true;
}

void adf4351_rf_enable(bool on) { rf_on = on; }
#endif
