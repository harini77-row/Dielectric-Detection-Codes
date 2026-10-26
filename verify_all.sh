#!/usr/bin/env bash
# Runs every check that does not need hardware. Skips what is not installed.
set -u
cd "$(dirname "$0")"
ok=0
step() { echo; echo "== $*"; }

step "host unit + integration tests (pytest)"
( cd host && python3 -m pytest -q tests ) || ok=1

step "PIO comparator: assemble, compare with pioasm (if built), emulate"
hdr=""
[ -f firmware/pico2/build/consistency.pio.h ] && hdr="--header firmware/pico2/build/consistency.pio.h"
python3 tools/pio_emu.py $hdr --n 100000 || ok=1

step "commit-gate invariant (Icarus Verilog)"
if command -v iverilog >/dev/null; then
  iverilog -g2012 -o /tmp/pgdd_tb verilog/commit_gate.v verilog/tb_commit_gate.v && vvp /tmp/pgdd_tb | grep -E "PASS|FAIL|records" || ok=1
else echo "iverilog not installed - skipped"; fi

step "firmware build (needs PICO_SDK_PATH and arm-none-eabi-gcc)"
if [ -n "${PICO_SDK_PATH:-}" ] && command -v arm-none-eabi-gcc >/dev/null; then
  cmake -S firmware/pico2 -B firmware/pico2/build -DCMAKE_BUILD_TYPE=Release >/dev/null && \
  cmake --build firmware/pico2/build -j >/dev/null && ls -l firmware/pico2/build/pgdd_trusted.uf2 || ok=1
else echo "PICO_SDK_PATH or toolchain missing - skipped"; fi

step "end-to-end simulated demo"
( cd host && python3 -m pgdd.cli sim-demo --root /tmp/pgdd_demo_$$ ) || ok=1

echo; [ $ok -eq 0 ] && echo "ALL CHECKS PASSED" || echo "SOME CHECKS FAILED"
exit $ok
