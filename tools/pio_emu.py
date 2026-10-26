#!/usr/bin/env python3
"""Instruction-level emulator for the consistency comparator PIO program.

Assembles the subset of PIO used by firmware/pico2/src/consistency.pio
(pull, push, mov, jmp) to the real 16-bit encodings, optionally cross-checks
them against the pioasm-generated header, then executes the program on
random and boundary inputs and checks:

  token emitted  <=>  gate_model.predicate(words)       (bit-exact rule)
  exactly 8 words consumed per record                   (framing never slips)
  program never writes anything except the RX FIFO     (by construction: the
                                                         subset has no memory op)

Usage: python3 tools/pio_emu.py [--header build/consistency.pio.h] [--n 200000]

This is behavioural verification of the program logic. It does not model
DREQ/DMA timing, which is deferred to the logic-analyser capture.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
from pgdd import gate_model  # noqa: E402

PIO_SRC = ROOT / "firmware/pico2/src/consistency.pio"

MOV_DST = {"pins": 0, "x": 1, "y": 2, "exec": 4, "pc": 5, "isr": 6, "osr": 7}
MOV_SRC = {"pins": 0, "x": 1, "y": 2, "null": 3, "status": 5, "isr": 6, "osr": 7}
JMP_COND = {"": 0, "!x": 1, "x--": 2, "!y": 3, "y--": 4, "x!=y": 5, "pin": 6, "!osre": 7}


def assemble(src: str):
    lines, labels, wrap_target, wrap = [], {}, 0, None
    in_prog = False
    for raw in src.splitlines():
        line = raw.split(";")[0].strip()
        if line.startswith("%"):
            break
        if not line:
            continue
        if line.startswith(".program"):
            in_prog = True
            continue
        if not in_prog:
            continue
        if line == ".wrap_target":
            wrap_target = len(lines); continue
        if line == ".wrap":
            wrap = len(lines) - 1; continue
        if line.endswith(":"):
            labels[line[:-1]] = len(lines); continue
        lines.append(line)
    words = []
    for ln in lines:
        t = ln.replace(",", " ").split()
        op = t[0]
        if op == "pull":
            block = "noblock" not in t
            words.append(0x8080 | (0x20 if block else 0))
        elif op == "push":
            block = "noblock" not in t
            words.append(0x0000 | 0x8000 | (0x20 if block else 0))
        elif op == "mov":
            dst, src = t[1], t[2]
            opbits = 0
            if src.startswith("~") or src.startswith("!"):
                opbits, src = 1, src[1:]
            words.append(0xA000 | (MOV_DST[dst] << 5) | (opbits << 3) | MOV_SRC[src])
        elif op == "jmp":
            if len(t) == 2:
                cond, target = "", t[1]
            else:
                cond, target = t[1], t[2]
            words.append(0x0000 | (JMP_COND[cond] << 5) | labels[target])
        else:
            raise ValueError(f"unsupported instruction: {ln}")
    return words, wrap_target, (wrap if wrap is not None else len(words) - 1)


def parse_header(path: Path):
    txt = path.read_text()
    return [int(h, 16) for h in re.findall(r"0x([0-9a-f]{4}),\s*//\s*\d+:", txt)]


class SM:
    def __init__(self, prog, wrap_target, wrap):
        self.p, self.wt, self.w = prog, wrap_target, wrap
        self.pc = 0
        self.x = self.y = self.osr = self.isr = 0
        self.tx, self.rx = [], []
        self.consumed = 0

    def step(self) -> bool:
        """Execute one instruction; returns False if stalled on an empty TX FIFO."""
        ins = self.p[self.pc]
        nxt = self.pc + 1 if self.pc != self.w else self.wt
        top = ins >> 13
        if top == 0b000:                       # JMP
            cond, addr = (ins >> 5) & 7, ins & 0x1F
            take = {0: True, 5: self.x != self.y}[cond]
            self.pc = addr if take else nxt
        elif top == 0b100 and ins & 0x80:      # PULL
            if not self.tx:
                return False
            self.osr = self.tx.pop(0)
            self.consumed += 1
            self.pc = nxt
        elif top == 0b100:                     # PUSH
            self.rx.append(self.isr)
            self.isr = 0
            self.pc = nxt
        elif top == 0b101:                     # MOV
            dst, opb, src = (ins >> 5) & 7, (ins >> 3) & 3, ins & 7
            v = {1: self.x, 2: self.y, 3: 0, 6: self.isr, 7: self.osr}[src]
            if opb == 1:
                v = (~v) & 0xFFFFFFFF
            if dst == 1: self.x = v
            elif dst == 2: self.y = v
            elif dst == 6: self.isr = v
            elif dst == 7: self.osr = v
            else: raise RuntimeError("unexpected mov dst")
            self.pc = nxt
        else:
            raise RuntimeError(f"unexpected opcode {ins:04x}")
        return True

    def run_record(self, words):
        assert len(words) == 8
        self.tx.extend(words)
        start_rx, start_c = len(self.rx), self.consumed
        for _ in range(1000):
            if not self.step():
                break
        return len(self.rx) - start_rx, self.consumed - start_c


def main(argv=None):
    import random
    ap = argparse.ArgumentParser()
    ap.add_argument("--header", type=Path)
    ap.add_argument("--n", type=int, default=100000)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)

    prog, wt, wr = assemble(PIO_SRC.read_text())
    print(f"assembled {len(prog)} instructions (limit 32), wrap {wt}..{wr}")
    assert len(prog) <= 32
    if a.header:
        hw = parse_header(a.header)
        assert hw == prog, "assembler output differs from pioasm header"
        print("matches pioasm output word-for-word")

    rng = random.Random(a.seed)
    sm = SM(prog, wt, wr)
    acc = rej = 0
    mb, pb = gate_model.MAG_BIN, gate_model.PHS_BIN
    for i in range(a.n):
        base_m = rng.randint(8000, 30000)
        base_p = rng.randint(0, 30000)
        # concentrate around the decision boundary
        dm = rng.choice([0, 1, mb // 2 - 1, mb // 2, mb - 1, mb, mb + 1, rng.randint(-3 * mb, 3 * mb)])
        dp = rng.choice([0, 1, pb // 2 - 1, pb // 2, pb - 1, pb, pb + 1, rng.randint(-3 * pb, 3 * pb)])
        dm *= rng.choice([-1, 1]); dp *= rng.choice([-1, 1])
        poison = rng.random() < 0.05
        w = gate_model.grid_words(base_m, base_m + dm, base_p, base_p + dp, poison=poison)
        tok, used = sm.run_record(w)
        want = gate_model.predicate(w)
        assert used == 8, f"record {i}: consumed {used} words"
        assert tok == int(want), f"record {i}: token {tok} predicate {want} words {w}"
        # guarantees of the dual-grid rule
        if not poison and abs(dm) < mb // 2 and abs(dp) < pb // 2:
            assert tok == 1
        if poison or abs(dm) >= mb or abs(dp) >= pb:
            assert tok == 0
        acc += tok; rej += 1 - tok
    print(f"{a.n} records: {acc} admitted, {rej} rejected; PIO == model on all; framing intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
