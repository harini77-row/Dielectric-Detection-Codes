// record.h — the on-wire / in-ring record. 64 bytes, little-endian.
// The host parser (host/pgdd/record.py) mirrors this layout exactly.
#pragma once
#include <stdint.h>
#include <assert.h>

#define REC_MAGIC     0x44444750u   // "PGDD" little-endian
#define REC_VERSION   1u
#define REC_COMMITTED 0xFFFFFFFFu   // value only the PIO token DMA ever writes

// flags
#define REC_F_ENROL   (1u << 0)     // session mode: enrolment
#define REC_F_VERIFY  (1u << 1)     // session mode: verification
#define REC_F_LOCK_A  (1u << 2)     // PLL locked during view A
#define REC_F_LOCK_B  (1u << 3)     // PLL locked during view B
#define REC_F_TEMP_OK (1u << 4)     // DS18B20 read valid

typedef struct __attribute__((packed, aligned(4))) {
    uint32_t commit;        // 0  written ONLY by the token DMA channel
    uint32_t magic;         // 4
    uint16_t version;       // 8
    uint16_t flags;         // 10
    uint32_t seq;           // 12 monotonic per boot, includes rejected attempts
    uint64_t t_us;          // 16 RP2350 64-bit hardware timer at view-B end
    uint32_t container_id;  // 24
    uint16_t session_id;    // 28
    uint8_t  angle_idx;     // 30 from trusted cradle counter / encoder
    uint8_t  port;          // 31 RF switch port
    uint32_t freq_khz;      // 32
    int16_t  vmag_a;        // 36 ADS1115 codes, averaged
    int16_t  vphs_a;        // 38
    int16_t  vmag_b;        // 40
    int16_t  vphs_b;        // 42
    int16_t  temp_c16;      // 44 deg C * 16 (DS18B20 native)
    uint16_t n_avg;         // 46
    uint32_t boot_id;       // 48 random per boot (ROSC), ties seq to a boot
    uint8_t  plan_id;       // 52
    uint8_t  n_angles;      // 53
    uint16_t reserved0;     // 54
    uint32_t commit_idx;    // 56 ring index if committed (contiguous; seq gaps = rejects)
    uint32_t crc32;         // 60 CRC-32/IEEE over bytes 4..59
} record_t;

static_assert(sizeof(record_t) == 64, "record_t must be 64 bytes");
#define REC_WORDS (sizeof(record_t) / 4)
#define REC_BODY_OFFSET 4                    // bytes after commit word
#define REC_BODY_WORDS  (REC_WORDS - 1)

uint32_t rec_crc32(const void *data, uint32_t len);
void     rec_seal(record_t *r);              // fills magic/version/crc
