// config.h — pin map and compile-time parameters for the trusted acquisition
// controller (Raspberry Pi Pico 2 / RP2350).
//
// Everything that decides *what gets measured and how a record is admitted*
// lives here, in the trusted domain. The Pi 5 can request a session by plan
// ID but cannot supply frequencies, tolerances, angles or record content.
#pragma once

// ---------------------------------------------------------------- ADF4351
#define ADF_SPI            spi0
#define ADF_PIN_SCK        18
#define ADF_PIN_MOSI       19
#define ADF_PIN_LE         17      // latch enable (acts as CS)
#define ADF_PIN_CE         20      // chip enable
#define ADF_PIN_LD         21      // lock detect input (R5 LD pin = digital LD)
#define ADF_REF_HZ         25000000u   // module crystal; change if yours is 10 MHz
#define ADF_CHAN_SPACING_HZ 100000u    // -> MOD = PFD / spacing = 250
#define ADF_OUT_POWER      3       // 0..3 => -4, -1, +2, +5 dBm
#define ADF_LOCK_TIMEOUT_US 5000u
#define ADF_PARK_HZ        2200000000ull // parking frequency between view A and B

// ---------------------------------------------------------------- ADS1115
#define ADS_I2C            i2c0
#define ADS_PIN_SDA        4
#define ADS_PIN_SCL        5
#define ADS_ADDR           0x48
#define ADS_CH_VMAG        0       // AIN0 <- AD8302 VMAG (via RC filter)
#define ADS_CH_VPHS        1       // AIN1 <- AD8302 VPHS (via RC filter)
#define ADS_N_AVG          8       // conversions averaged per view per channel
// RC filter settling after a frequency step (match to your R and C; with
// 10k/100nF tau = 1 ms -> 7 tau = 7 ms). 1 uF is NOT usable (see notes).
#define RC_SETTLE_US       7000u

// ---------------------------------------------------------------- DS18B20
#define DS_PIN             22

// ---------------------------------------------------------------- RF switch
// SP4T kept for the optional multi-port build. Single-antenna S11 build uses
// port 0 only (N_PORTS = 1).
#define SW_PIN_V1          2
#define SW_PIN_V2          3
#define N_PORTS            1

// ---------------------------------------------------------------- Cradle
// Angle provenance must originate in the trusted domain. Two options:
//   CRADLE_MODE_BUTTON : firmware owns the angle counter; operator rotates to
//                        the next detent and presses the step button.
//   CRADLE_MODE_ENCODER: 4-bit absolute index read from slot/reed sensors.
#define CRADLE_MODE_BUTTON   0
#define CRADLE_MODE_ENCODER  1
#define CRADLE_MODE          CRADLE_MODE_BUTTON
#define CRADLE_PIN_BUTTON    28
#define CRADLE_PIN_ENC0      7     // ENC0..ENC3 = GP7..GP10
#define CRADLE_N_ANGLES_MAX  12

// ---------------------------------------------------------------- Host link
// SPI1 as *peripheral* (slave). The Pi 5 is controller. Mode 3 so CS can stay
// low across a whole frame on the PL022.
#define HOST_SPI           spi1
#define HOST_PIN_RX        12      // Pi MOSI -> Pico
#define HOST_PIN_CSN       13
#define HOST_PIN_SCK       14
#define HOST_PIN_TX        15      // Pico -> Pi MISO
#define HOST_PIN_DRDY      16      // high = a committed frame is loaded

// ---------------------------------------------------------------- Debug
// Pulses for the logic-analyser capture that demonstrates "reject => no bus
// traffic". These pins are NOT connected to the Pi.
#define DBG_PIN_REJECT     26
#define DBG_PIN_COMMIT     27

// ---------------------------------------------------------------- Gate
// Dual-grid quantisation. Bin width in ADS1115 codes (62.5 uV/LSB @ +-2.048 V).
// AD8302: 30 mV/dB -> 480 codes/dB ; 10 mV/deg -> 160 codes/deg.
// Guaranteed accept if |A-B| < BIN/2 ; guaranteed reject if |A-B| >= BIN.
#define GATE_MAG_BIN_CODES 64      // ~0.13 dB
#define GATE_PHS_BIN_CODES 64      // ~0.40 deg
#define GATE_TIMEOUT_US    2000u
#define GATE_PIO           pio0

// ---------------------------------------------------------------- Ring
#define RING_SLOTS         64      // power of two
