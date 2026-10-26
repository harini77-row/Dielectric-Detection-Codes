#include "record.h"

// Reflected CRC-32 (IEEE 802.3), identical to Python zlib.crc32.
uint32_t rec_crc32(const void *data, uint32_t len) {
    const uint8_t *p = (const uint8_t *)data;
    uint32_t crc = 0xFFFFFFFFu;
    while (len--) {
        crc ^= *p++;
        for (int k = 0; k < 8; k++)
            crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)-(int32_t)(crc & 1u));
    }
    return ~crc;
}

void rec_seal(record_t *r) {
    r->commit  = 0;                       // never set by the CPU
    r->magic   = REC_MAGIC;
    r->version = REC_VERSION;
    r->crc32   = rec_crc32((const uint8_t *)r + 4, 56);
}
