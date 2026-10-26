// commit_gate.c — PIO comparator + DMA commit path.
//
//   record builder (CPU)                     ring[] (only DMA writes here)
//        |  8 quantised words                  ^            ^
//        v                                     | body copy  | commit word
//   PIO SM "consistency" --token--> RX FIFO ---DREQ---> DMA T --chain--> DMA C
//
// The CPU arms T and C, pushes the grid words, and waits. It never copies the
// record into the ring itself. If the comparator withholds the token, T is
// never paced, C is never chained, and the slot stays empty; the host link
// only ever serves slots below ring_head().
#include "commit_gate.h"
#include "config.h"
#include "pico/stdlib.h"
#include "hardware/pio.h"
#include "hardware/dma.h"
#include "hardware/sync.h"
#include "consistency.pio.h"
#include <string.h>

static record_t ring[RING_SLOTS] __attribute__((aligned(64)));
static volatile uint32_t head;   // committed count  (main context writes)
static volatile uint32_t tail;   // sent count       (link IRQ writes)

static PIO  pio = GATE_PIO;
static uint sm;
static int  ch_tok, ch_body;
static uint32_t tok_sink_unused;
static gate_stats_t stats;

static_assert((RING_SLOTS & (RING_SLOTS - 1)) == 0, "RING_SLOTS power of two");

void gate_init(void) {
    uint offset = pio_add_program(pio, &consistency_program);
    sm = (uint)pio_claim_unused_sm(pio, true);
    consistency_program_init(pio, sm, offset);

    ch_tok  = dma_claim_unused_channel(true);
    ch_body = dma_claim_unused_channel(true);
    memset(ring, 0, sizeof ring);
    head = tail = 0;
    (void)tok_sink_unused;

    gpio_init(DBG_PIN_REJECT); gpio_set_dir(DBG_PIN_REJECT, GPIO_OUT); gpio_put(DBG_PIN_REJECT, 0);
    gpio_init(DBG_PIN_COMMIT); gpio_set_dir(DBG_PIN_COMMIT, GPIO_OUT); gpio_put(DBG_PIN_COMMIT, 0);
}

static inline uint32_t q(int16_t code, uint32_t bin, uint32_t off) {
    return ((uint32_t)((int32_t)code + 32768) + off) / bin;
}

static void pulse(uint pin) { gpio_put(pin, 1); busy_wait_us_32(2); gpio_put(pin, 0); }

gate_result_t gate_submit(const record_t *staged, bool poison) {
    if (head - tail >= RING_SLOTS) return GATE_RING_FULL;

    // Precondition: comparator idle with empty FIFOs. A stale token here
    // would admit the next record unchecked, so treat it as a fault.
    if (!pio_sm_is_rx_fifo_empty(pio, sm) || !pio_sm_is_tx_fifo_empty(pio, sm)) {
        while (!pio_sm_is_rx_fifo_empty(pio, sm)) (void)pio_sm_get(pio, sm);
        stats.faults++;
        return GATE_FAULT;
    }

    record_t *slot = &ring[head & (RING_SLOTS - 1)];
    slot->commit = 0;

    // C: unpaced body copy, armed but not triggered.
    dma_channel_config cc = dma_channel_get_default_config(ch_body);
    channel_config_set_transfer_data_size(&cc, DMA_SIZE_32);
    channel_config_set_read_increment(&cc, true);
    channel_config_set_write_increment(&cc, true);
    channel_config_set_dreq(&cc, DREQ_FORCE);
    dma_channel_configure(ch_body, &cc,
                          (uint32_t *)slot + 1, (const uint32_t *)staged + 1,
                          REC_BODY_WORDS, false);

    // T: one word from the PIO RX FIFO into slot->commit, paced by PIO DREQ.
    dma_channel_config tc = dma_channel_get_default_config(ch_tok);
    channel_config_set_transfer_data_size(&tc, DMA_SIZE_32);
    channel_config_set_read_increment(&tc, false);
    channel_config_set_write_increment(&tc, false);
    channel_config_set_dreq(&tc, pio_get_dreq(pio, sm, false));
    channel_config_set_chain_to(&tc, ch_body);

    dma_hw->intr = (1u << ch_body);                       // clear stale done flag
    dma_channel_configure(ch_tok, &tc, &slot->commit, &pio->rxf[sm], 1, true);

    // Feed the comparator.
    const uint32_t mb = GATE_MAG_BIN_CODES, pb = GATE_PHS_BIN_CODES;
    uint32_t w[8] = {
        q(staged->vmag_a, mb, 0),      q(staged->vmag_b, mb, 0),
        q(staged->vmag_a, mb, mb / 2), q(staged->vmag_b, mb, mb / 2),
        q(staged->vphs_a, pb, 0),      q(staged->vphs_b, pb, 0),
        q(staged->vphs_a, pb, pb / 2), q(staged->vphs_b, pb, pb / 2),
    };
    if (poison) { w[1] = ~w[0]; w[3] = ~w[2]; w[5] = ~w[4]; w[7] = ~w[6]; }
    for (int i = 0; i < 8; i++) pio_sm_put_blocking(pio, sm, w[i]);

    absolute_time_t dl = make_timeout_time_us(GATE_TIMEOUT_US);
    while (!(dma_hw->intr & (1u << ch_body))) {
        if (time_reached(dl)) {
            // Rejected. Detach the chain before aborting so an abort can
            // never trigger the body copy, then abort both.
            channel_config_set_chain_to(&tc, ch_tok);
            dma_channel_set_config(ch_tok, &tc, false);
            dma_channel_abort(ch_tok);
            dma_channel_abort(ch_body);
            dma_hw->intr = (1u << ch_tok) | (1u << ch_body);
            if (slot->commit != 0) { stats.faults++; slot->commit = 0; return GATE_FAULT; }
            stats.rejected++;
            pulse(DBG_PIN_REJECT);
            return GATE_REJECTED;
        }
    }
    dma_hw->intr = (1u << ch_body);
    if (slot->commit != REC_COMMITTED) { stats.faults++; return GATE_FAULT; }

    __dmb();
    head = head + 1;
    stats.committed++;
    pulse(DBG_PIN_COMMIT);
    return GATE_COMMITTED;
}

uint32_t        ring_head(void)            { return head; }
uint32_t        ring_tail(void)            { return tail; }
const record_t *ring_slot(uint32_t idx)    { return &ring[idx & (RING_SLOTS - 1)]; }
void            ring_set_tail(uint32_t t)  { tail = t; }
const gate_stats_t *gate_stats(void)       { return &stats; }
