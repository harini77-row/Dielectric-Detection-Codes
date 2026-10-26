"""Bit-exact Python model of the trusted comparator (consistency.pio + the
quantiser in commit_gate.c). Used by the simulator so simulated records are
admitted by the same rule as hardware. tools/pio_emu.py checks this model
against the assembled PIO program."""
from __future__ import annotations

MAG_BIN = 64
PHS_BIN = 64


def q(code: int, binw: int, off: int) -> int:
    return ((code + 32768) + off) // binw


def grid_words(vmag_a: int, vmag_b: int, vphs_a: int, vphs_b: int,
               mag_bin: int = MAG_BIN, phs_bin: int = PHS_BIN, poison: bool = False) -> list[int]:
    w = [q(vmag_a, mag_bin, 0), q(vmag_b, mag_bin, 0),
         q(vmag_a, mag_bin, mag_bin // 2), q(vmag_b, mag_bin, mag_bin // 2),
         q(vphs_a, phs_bin, 0), q(vphs_b, phs_bin, 0),
         q(vphs_a, phs_bin, phs_bin // 2), q(vphs_b, phs_bin, phs_bin // 2)]
    if poison:
        for i in (1, 3, 5, 7):
            w[i] = (~w[i - 1]) & 0xFFFFFFFF
    return w


def predicate(w: list[int]) -> bool:
    return (w[0] == w[1] or w[2] == w[3]) and (w[4] == w[5] or w[6] == w[7])


def admit(vmag_a: int, vmag_b: int, vphs_a: int, vphs_b: int, poison: bool = False,
          mag_bin: int = MAG_BIN, phs_bin: int = PHS_BIN) -> bool:
    return predicate(grid_words(vmag_a, vmag_b, vphs_a, vphs_b, mag_bin, phs_bin, poison))
