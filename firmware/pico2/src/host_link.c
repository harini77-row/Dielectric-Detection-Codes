// host_link.c — SPI1 as peripheral. The Pi 5 is controller and clocks fixed
// 64-byte frames. Each frame simultaneously
//   Pico -> Pi : a committed ring slot (DRDY high) or a status frame (DRDY low)
//   Pi -> Pico : a host_cmd_t (request + cumulative ack)
// The only memory the TX DMA can read is a committed slot or the status
// buffer. A rejected record was never placed in a slot, so it has no path here.
#include "host_link.h"
#include "commit_gate.h"
#include "record.h"
#include "config.h"
#include "pico/stdlib.h"
#include "hardware/spi.h"
#include "hardware/dma.h"
#include "hardware/sync.h"
#include <string.h>

static int ch_tx, ch_rx;
static uint8_t rxbuf[64] __attribute__((aligned(4)));
static status_frame_t status __attribute__((aligned(4)));
static volatile bool     armed_is_record;
static volatile uint32_t sendptr;           // next commit index to transmit
static volatile bool     cmd_ready;
static host_cmd_t        cmd_mailbox;
static uint32_t          boot_id;
static volatile uint8_t  st_state, st_angle;
static volatile uint16_t st_session;

static void spi_setup(void) {
    spi_init(HOST_SPI, 10000000);          // resets the PL022: flushes FIFOs
    spi_set_slave(HOST_SPI, true);
    spi_set_format(HOST_SPI, 8, SPI_CPOL_1, SPI_CPHA_1, SPI_MSB_FIRST);
}

static void build_status(void) {
    memset(&status, 0, sizeof status);
    status.magic = STAT_MAGIC;
    status.boot_id = boot_id;
    status.head = ring_head();
    status.state = st_state;
    status.angle = st_angle;
    status.session_id = st_session;
    status.crc32 = rec_crc32((const uint8_t *)&status + 4, 56);
}

static void arm(void) {
    dma_channel_abort(ch_tx);
    dma_channel_abort(ch_rx);
    spi_setup();

    const void *src;
    if (ring_head() > sendptr) {
        src = ring_slot(sendptr);
        armed_is_record = true;
    } else {
        build_status();
        src = &status;
        armed_is_record = false;
    }

    dma_channel_config rc = dma_channel_get_default_config(ch_rx);
    channel_config_set_transfer_data_size(&rc, DMA_SIZE_8);
    channel_config_set_read_increment(&rc, false);
    channel_config_set_write_increment(&rc, true);
    channel_config_set_dreq(&rc, spi_get_dreq(HOST_SPI, false));
    dma_channel_configure(ch_rx, &rc, rxbuf, &spi_get_hw(HOST_SPI)->dr, 64, true);

    dma_channel_config tc = dma_channel_get_default_config(ch_tx);
    channel_config_set_transfer_data_size(&tc, DMA_SIZE_8);
    channel_config_set_read_increment(&tc, true);
    channel_config_set_write_increment(&tc, false);
    channel_config_set_dreq(&tc, spi_get_dreq(HOST_SPI, true));
    dma_channel_configure(ch_tx, &tc, &spi_get_hw(HOST_SPI)->dr, src, 64, true);

    gpio_put(HOST_PIN_DRDY, armed_is_record);
}

static void handle_cmd(void) {
    host_cmd_t c;
    memcpy(&c, rxbuf, sizeof c);
    if (c.magic != CMD_MAGIC) return;
    if (rec_crc32(&c, 60) != c.crc32) return;

    uint32_t t = ring_tail();
    if (c.ack >= t && c.ack <= sendptr) ring_set_tail(c.ack);
    if (c.nack) sendptr = (c.ack >= ring_tail()) ? c.ack : ring_tail();   // go-back-N

    if (c.cmd != CMD_NOP) { cmd_mailbox = c; cmd_ready = true; }
}

// CSn rising edge = end of a frame (complete or torn).
static void cs_irq(uint gpio, uint32_t events) {
    if (gpio != HOST_PIN_CSN || !(events & GPIO_IRQ_EDGE_RISE)) return;
    uint32_t remaining = dma_channel_hw_addr(ch_rx)->transfer_count & 0x0FFFFFFFu;
    if (remaining == 0) {
        if (armed_is_record) sendptr = sendptr + 1;
        handle_cmd();
    }
    arm();                                   // torn frame -> same frame re-armed
}

void host_link_init(uint32_t bid) {
    boot_id = bid;
    gpio_init(HOST_PIN_DRDY); gpio_set_dir(HOST_PIN_DRDY, GPIO_OUT); gpio_put(HOST_PIN_DRDY, 0);
    gpio_set_function(HOST_PIN_RX,  GPIO_FUNC_SPI);
    gpio_set_function(HOST_PIN_CSN, GPIO_FUNC_SPI);
    gpio_set_function(HOST_PIN_SCK, GPIO_FUNC_SPI);
    gpio_set_function(HOST_PIN_TX,  GPIO_FUNC_SPI);
    ch_tx = dma_claim_unused_channel(true);
    ch_rx = dma_claim_unused_channel(true);
    sendptr = 0;
    arm();
    gpio_set_irq_enabled_with_callback(HOST_PIN_CSN, GPIO_IRQ_EDGE_RISE, true, &cs_irq);
}

void host_link_set_state(uint8_t s, uint8_t a, uint16_t sid) {
    st_state = s; st_angle = a; st_session = sid;
}

bool host_link_take_cmd(host_cmd_t *out) {
    if (!cmd_ready) return false;
    uint32_t s = save_and_disable_interrupts();
    *out = cmd_mailbox;
    cmd_ready = false;
    restore_interrupts(s);
    return true;
}

void host_link_poll(void) {
    // Swap an armed status frame for a newly committed record, but only
    // while the controller is not mid-frame.
    uint32_t s = save_and_disable_interrupts();
    if (!armed_is_record && ring_head() > sendptr && gpio_get(HOST_PIN_CSN)) {
        uint32_t remaining = dma_channel_hw_addr(ch_rx)->transfer_count & 0x0FFFFFFFu;
        if (remaining == 64) arm();
    }
    restore_interrupts(s);
}
