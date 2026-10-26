// main.c — trusted acquisition controller (Raspberry Pi Pico 2 / RP2350)
//
// Session = for each cradle angle: read temperature, then for each frequency in
// the ROM plan: tune -> settle -> view A -> park -> re-tune -> settle -> view B
// -> assemble record (hardware timestamp) -> submit to the commit gate.
// View A and view B are separate PLL lock events, so the comparator checks
// repeatability of the whole chain, not just ADC noise.
#include <stdio.h>
#include <string.h>
#include "pico/stdlib.h"
#include "pico/rand.h"
#include "config.h"
#include "record.h"
#include "adf4351.h"
#include "ads1115.h"
#include "ds18b20.h"
#include "cradle.h"
#include "commit_gate.h"
#include "host_link.h"

// ------------------------------------------------------------ frequency plans
// Fixed in ROM: the host selects a plan by ID, never supplies frequencies.
typedef struct { uint32_t start_khz, stop_khz, step_khz; } plan_t;
static const plan_t PLANS[] = {
    { 2300000, 2500000, 10000 },   // 0: 21 points, default
    { 2300000, 2500000,  5000 },   // 1: 41 points
    { 2400000, 2400000,  1000 },   // 2: single point (bring-up / logic analyser)
    { 2350000, 2450000, 25000 },   // 3: 5 points (quick check)
};
#define N_PLANS (sizeof PLANS / sizeof PLANS[0])

static uint32_t boot_id, seq;
static volatile bool abort_req;

static void service_link(void) {
    host_link_poll();
    host_cmd_t c;
    if (host_link_take_cmd(&c) && c.cmd == CMD_ABORT) abort_req = true;
}

static void wait_us_servicing(uint32_t us) {
    absolute_time_t dl = make_timeout_time_us(us);
    while (!time_reached(dl)) service_link();
}

// One view: returns false on ADC failure. Lock state reported separately.
static bool take_view(uint64_t f_hz, bool *locked, int16_t *mag, int16_t *phs) {
    adf4351_plan_t p;
    *locked = adf4351_tune(f_hz, &p);
    wait_us_servicing(RC_SETTLE_US);
    *locked = *locked && adf4351_locked();
    bool ok = ads1115_read_avg(ADS_CH_VMAG, ADS_N_AVG, mag) &&
              ads1115_read_avg(ADS_CH_VPHS, ADS_N_AVG, phs);
    *locked = *locked && adf4351_locked();     // still locked after conversion
    return ok;
}

static void run_session(const host_cmd_t *c) {
    if (c->plan_id >= N_PLANS || c->n_angles == 0 || c->n_angles > CRADLE_N_ANGLES_MAX ||
        (c->mode != MODE_ENROL && c->mode != MODE_VERIFY)) {
        printf("session rejected: bad parameters\n");
        host_link_set_state(0, 0, c->session_id);    // lets the host see it ended
        return;
    }
    const plan_t *pl = &PLANS[c->plan_id];
    abort_req = false;
    printf("session %u container %lu mode %u plan %u angles %u\n",
           c->session_id, (unsigned long)c->container_id, c->mode, c->plan_id, c->n_angles);

    for (uint8_t a = 0; a < c->n_angles && !abort_req; a++) {
        host_link_set_state(2, a, c->session_id);
        printf("  rotate cradle to angle %u and press step\n", a);
        int ang = -1;
        while (ang < 0 && !abort_req) {
            ang = cradle_wait_angle(a, 250);
            service_link();
        }
        if (abort_req) break;
        host_link_set_state(1, a, c->session_id);

        int16_t t16 = 0;
        bool t_ok = ds18b20_read(&t16);

        for (uint32_t fk = pl->start_khz; fk <= pl->stop_khz && !abort_req; fk += pl->step_khz) {
            for (uint8_t port = 0; port < N_PORTS; port++) {
                rfsw_select(port);
                uint64_t f = (uint64_t)fk * 1000ull;

                record_t r;
                memset(&r, 0, sizeof r);
                bool la, lb, oka, okb;
                oka = take_view(f, &la, &r.vmag_a, &r.vphs_a);
                adf4351_plan_t park;
                adf4351_tune(ADF_PARK_HZ, &park);       // force an independent relock
                okb = take_view(f, &lb, &r.vmag_b, &r.vphs_b);

                adf4351_plan_t act;
                adf4351_compute(f, &act);
                r.t_us         = time_us_64();
                r.seq          = seq++;
                r.boot_id      = boot_id;
                r.container_id = c->container_id;
                r.session_id   = c->session_id;
                r.angle_idx    = (uint8_t)ang;
                r.port         = port;
                r.freq_khz     = (uint32_t)(act.actual_hz / 1000ull);
                r.temp_c16     = t16;
                r.n_avg        = ADS_N_AVG;
                r.plan_id      = c->plan_id;
                r.n_angles     = c->n_angles;
                r.commit_idx   = ring_head();
                r.flags        = (c->mode == MODE_ENROL ? REC_F_ENROL : REC_F_VERIFY) |
                                 (la ? REC_F_LOCK_A : 0) | (lb ? REC_F_LOCK_B : 0) |
                                 (t_ok ? REC_F_TEMP_OK : 0);
                rec_seal(&r);

                bool poison = !(la && lb && oka && okb);
                gate_result_t g;
                int tries = 0;
                while ((g = gate_submit(&r, poison)) == GATE_RING_FULL && tries++ < 5000) {
                    wait_us_servicing(1000);           // host not draining: back-pressure
                }
                if (g == GATE_RING_FULL) { printf("ring full, aborting\n"); abort_req = true; }
                service_link();
            }
        }
    }
    host_link_set_state(0, 0, c->session_id);
    const gate_stats_t *s = gate_stats();
    printf("session done: committed %lu rejected %lu faults %lu\n",
           (unsigned long)s->committed, (unsigned long)s->rejected, (unsigned long)s->faults);
}

int main(void) {
    stdio_init_all();                 // debug UART only; never wired to the Pi
    boot_id = get_rand_32();
    sleep_ms(500);
    printf("\nPGDD trusted controller, boot_id %08lx\n", (unsigned long)boot_id);

    adf4351_init();
    if (!ads1115_init()) printf("ADS1115 not responding\n");
    ds18b20_init();
    cradle_init();
    rfsw_init();
    gate_init();
    host_link_init(boot_id);

    for (;;) {
        host_cmd_t c;
        service_link();
        if (host_link_take_cmd(&c) && c.cmd == CMD_START) run_session(&c);
        tight_loop_contents();
    }
}
