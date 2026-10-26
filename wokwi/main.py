# Wokwi (MicroPython, Raspberry Pi Pico) - thin secondary demo of the
# consistency comparator logic ONLY.
#   pot on GP26 = view A, pot on GP27 = view B (stand-ins for VMAG; the
#   ADS1115 part does not exist in Wokwi, so the RP2040 internal ADC is used)
#   slide switch on GP16 = PLL lock (off -> poisoned -> must reject)
#   green LED GP15 = token emitted (would pace the commit DMA)
#   red LED GP14   = token withheld
# This does NOT demonstrate the DMA gate or "no SPI traffic on reject";
# that is a hardware claim for the logic-analyser capture.
import rp2
from machine import ADC, Pin
import time

MAG_BIN = 64
PHS_BIN = 64


@rp2.asm_pio()
def consistency():
    wrap_target()
    label("start")
    pull(block)
    mov(x, osr)
    pull(block)
    mov(y, osr)
    pull(block)
    jmp(x_not_y, "mag_g1")
    pull(block)
    jmp("phase")
    label("mag_g1")
    mov(x, osr)
    pull(block)
    mov(y, osr)
    jmp(x_not_y, "reject_ph")
    label("phase")
    pull(block)
    mov(x, osr)
    pull(block)
    mov(y, osr)
    pull(block)
    jmp(x_not_y, "ph_g1")
    pull(block)
    jmp("accept")
    label("ph_g1")
    mov(x, osr)
    pull(block)
    mov(y, osr)
    jmp(x_not_y, "start")
    label("accept")
    mov(isr, invert(null))
    push(block)
    jmp("start")
    label("reject_ph")
    pull(block)
    pull(block)
    pull(block)
    pull(block)
    wrap()


def q(code, b, off):
    return ((code + 32768) + off) // b


sm = rp2.StateMachine(0, consistency, freq=2_000_000)
sm.active(1)
adc_a, adc_b = ADC(26), ADC(27)
lock_sw = Pin(16, Pin.IN, Pin.PULL_DOWN)
led_ok, led_rej = Pin(15, Pin.OUT), Pin(14, Pin.OUT)
committed = rejected = 0

while True:
    a = adc_a.read_u16() >> 1          # 15-bit, like a positive ADS1115 code
    b = adc_b.read_u16() >> 1
    pa = pb = 9000                     # phase channel held constant in this demo
    w = [q(a, MAG_BIN, 0), q(b, MAG_BIN, 0), q(a, MAG_BIN, MAG_BIN // 2), q(b, MAG_BIN, MAG_BIN // 2),
         q(pa, PHS_BIN, 0), q(pb, PHS_BIN, 0), q(pa, PHS_BIN, PHS_BIN // 2), q(pb, PHS_BIN, PHS_BIN // 2)]
    if not lock_sw.value():            # poison: view-B words forced to differ
        for i in (1, 3, 5, 7):
            w[i] = (~w[i - 1]) & 0xFFFFFFFF
    for x_ in w:
        sm.put(x_)
    time.sleep_ms(2)
    tok = sm.rx_fifo() > 0
    if tok:
        sm.get()
        committed += 1
    else:
        rejected += 1
    led_ok.value(tok)
    led_rej.value(not tok)
    print("A=%5d B=%5d |A-B|=%4d lock=%d -> %s  (commit %d, reject %d)"
          % (a, b, abs(a - b), lock_sw.value(), "COMMIT" if tok else "reject", committed, rejected))
    time.sleep_ms(300)
