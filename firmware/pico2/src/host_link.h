#pragma once
#include <stdint.h>
#include <stdbool.h>

// Host -> Pico command frame (64 bytes, clocked in while a record/status frame
// is clocked out). The host can only *request*; it cannot write into the ring.
#define CMD_MAGIC  0x444D4348u   // "HCMD"
#define STAT_MAGIC 0x54534750u   // "PGST"

enum { CMD_NOP = 0, CMD_START = 1, CMD_ABORT = 2 };
enum { MODE_ENROL = 1, MODE_VERIFY = 2 };

typedef struct __attribute__((packed, aligned(4))) {
    uint32_t magic;          // 0
    uint8_t  cmd;            // 4
    uint8_t  mode;           // 5
    uint8_t  plan_id;        // 6
    uint8_t  n_angles;       // 7
    uint32_t container_id;   // 8
    uint16_t session_id;     // 12
    uint16_t host_seq;       // 14
    uint32_t ack;            // 16 cumulative count of record frames verified by host
    uint8_t  nack;           // 20 1 = last record frame failed CRC -> go back to `ack`
    uint8_t  pad[39];        // 21
    uint32_t crc32;          // 60 over bytes 0..59
} host_cmd_t;

// Pico -> host status frame, sent when no committed record is pending.
typedef struct __attribute__((packed, aligned(4))) {
    uint32_t commit;         // 0 always 0 (never a committed record)
    uint32_t magic;          // 4 STAT_MAGIC
    uint32_t boot_id;        // 8
    uint32_t head;           // 12 committed count this boot
    uint8_t  state;          // 16 0 idle, 1 running, 2 waiting cradle
    uint8_t  angle;          // 17
    uint16_t session_id;     // 18
    uint8_t  pad[40];        // 20
    uint32_t crc32;          // 60 over bytes 4..59
} status_frame_t;

void host_link_init(uint32_t boot_id);
// Main loop hands over session state so the status frame is meaningful.
void host_link_set_state(uint8_t state, uint8_t angle, uint16_t session_id);
// Non-blocking: returns true and fills *out if a valid command arrived.
bool host_link_take_cmd(host_cmd_t *out);
// Call often: if the link is idle with a status frame armed and a committed
// record is now available, swap it in.
void host_link_poll(void);
