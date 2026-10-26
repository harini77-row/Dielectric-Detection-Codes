# PGDD — provenance-gated dielectric drift detection

Code for the sealed-container dielectric-signature project: trusted acquisition on a
Raspberry Pi Pico 2 (RP2350), untrusted inversion host on a Raspberry Pi 5.

```
firmware/pico2/   trusted domain: ADF4351, ADS1115, DS18B20, cradle, PIO comparator,
                  DMA commit gate, SPI-peripheral host link            (C, pico-sdk 2.x)
host/pgdd/        untrusted domain: frame link + ack, calibration, reference store,
                  bootstrap-verified enrolment, hypotheses + quorum arbitration,
                  SHA-256 ledger, simulator, ablation, CLI              (Python 3.10+)
phase0/           VNA Touchstone import + nested-ANOVA variance decomposition (ICC)
matlab/           Assessment-4 models (forward model, AD8302, ANOVA, FSM reference,
                  enrolment, arbitration ablation, RC settling)          (MATLAB / Octave)
verilog/          commit-gate invariant testbench (behavioural, not a synthesis target)
tools/pio_emu.py  assembles + emulates consistency.pio, checks it against the Python model
wokwi/            comparator-logic demo with internal-ADC pots (thin secondary)
verify_all.sh     every check that does not need hardware
```

## Quick start (no hardware)

```bash
cd host && pip install -e .[test]
pgdd sim-demo --root runs/demo            # enrol 4 vials, verify 5 cases, check ledger
pgdd ablation --seeds 5 --out runs/ablation
cd .. && ./verify_all.sh
```

## Firmware

```bash
export PICO_SDK_PATH=/path/to/pico-sdk     # 2.1.x
cmake -S firmware/pico2 -B firmware/pico2/build && cmake --build firmware/pico2/build -j
# hold BOOTSEL, plug in, copy firmware/pico2/build/pgdd_trusted.uf2
```
Pins and every admission parameter are in `firmware/pico2/include/config.h`.
`ADF_REF_HZ` must match your ADF4351 module crystal (25 MHz assumed).
Debug console is UART0 (GP0/GP1), never wired to the Pi.

### Wiring

| Function | Pico 2 | Other end |
|---|---|---|
| ADF4351 CLK / DATA / LE / CE / LD | GP18 / GP19 / GP17 / GP20 / GP21 | module |
| ADS1115 SDA / SCL (0x48) | GP4 / GP5 | AIN0 = VMAG, AIN1 = VPHS (via RC) |
| DS18B20 DQ (4.7 k pull-up) | GP22 | cradle sensor |
| Cradle step button (to GND) | GP28 | encoder option: GP7–GP10 |
| SP4T V1 / V2 (multi-port build only) | GP2 / GP3 | switch |
| Host SPI1 RX / CSn / SCK / TX | GP12 / GP13 / GP14 / GP15 | Pi 5 MOSI GPIO10 (pin 19) / CE0 GPIO8 (24) / SCLK GPIO11 (23) / MISO GPIO9 (21) |
| DRDY | GP16 | Pi 5 GPIO25 (pin 22) |
| Logic-analyser only | GP26 = reject pulse, GP27 = commit pulse | not connected to Pi |
| GND | any | Pi GND (common) |

### Pi 5

```bash
sudo raspi-config nonint do_spi 0
pip install -e host[pi]
pgdd enrol  --container 101 --angles 8 --drdy gpiochip0:25   # gpiochip4 on older kernels
pgdd verify --container 101 --angles 8 --drdy gpiochip0:25
pgdd ledger-verify runs/bench/ledger.jsonl
pgdd features --root runs/bench                               # regenerates features.csv
```

## How the three claims map to code and evidence

1. **Structural admission gating** — `consistency.pio` emits a token only if view A and
   view B agree on both channels (dual-grid, ±½ bin guaranteed accept, ≥1 bin guaranteed
   reject). The token is the DREQ that paces DMA channel T, which writes the commit word
   and chains to channel C, the only writer of the ring. Lock loss / ADC failure poisons
   the words so they are rejected by the same path. `host_link.c` can only transmit ring
   slots below `head` or a status frame.
   *Evidence:* logic-analyser capture of GP26/GP27 + SPI1 with `--drdy` polling (reject
   pulses with no record frame); `tools/pio_emu.py` (PIO ≡ model, framing never slips);
   `verilog/tb_commit_gate.v` (`ring_we ↔ consistency` on 20 000 random records).
2. **Quorum + residual arbitration** — `host/pgdd/decide.py`. *Evidence:* `pgdd ablation`
   / `matlab/run_ablation.m` (5 fault modes × rates × seeds, gate on/off, confusion matrices).
3. **Bootstrap-verified enrolment** — `host/pgdd/enrollment.py`; `ReferenceStore.write`
   refuses anything without a passing certificate whose digest matches. *Evidence:* the
   ledger shows every `enrol_step` before `reference_write`; tests cover refusal and
   exclusion of a mis-seated detent.

## Record provenance

64-byte record: hardware timestamp, per-boot random `boot_id`, `seq` (every attempt),
`commit_idx` (committed only, contiguous), trusted angle index, ROM plan ID, temperature,
raw ADS1115 codes for both views, CRC-32. Interior `seq` gaps are the only trace of
rejects the host can see. The host acks cumulatively; CRC failures trigger go-back-N.

## Limitations (state them before an examiner does)

- Everything in `forward.py`, `matlab/`, `phase0/synth_phase0.py` and the ablations is
  **synthetic**; numbers describe the generator, not the system.
- The geometry yields a dielectric **signature** (amplitude_db, phase_deg, residual), not
  permittivity. No permittivity proxy is computed, to keep the ablation leakage-free.
- The AD8302 chain resolves ~0.1 dB / ~0.5°; the ~1 MHz shift in the base paper needs a
  VNA. Realistic target: gross substitution. Phase 0 (`phase0/variance_decomp.py`) decides.
- No temperature compensation yet: a large temperature excursion produces DRIFT or
  INCONCLUSIVE in the ablation. `temp_c16` is recorded for when it is added.
- `container_id` is an operator label carried for bookkeeping; a wrong label fails safe
  (mismatch), it is not an identity proof.
- PIO/DMA timing, DREQ arbitration, SPI timing and near-field EM are not simulated;
  they are hardware-validation items. PIO is a fixed 31-instruction program with no
  memory-write instruction, which is the precise sense of "outside the CPU".
- SPI-peripheral re-arm happens in the CSn-rise IRQ; the host waits 0.4 ms between frames.
