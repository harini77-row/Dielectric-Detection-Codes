"""Minimal Touchstone v1 reader (.s1p / .s2p) for VNA exports
(Keysight, EMQuest, etc.). Supports RI, MA and DB formats and Hz/kHz/MHz/GHz."""
from __future__ import annotations

from pathlib import Path

import numpy as np

UNITS = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}


def read(path) -> tuple[np.ndarray, np.ndarray]:
    """Returns (f_hz[N], S[N, nports, nports]) as complex."""
    path = Path(path)
    nports = int(path.suffix.lower().strip(".s").rstrip("p"))
    unit, fmt = "ghz", "ma"
    vals = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.split("!")[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            t = line[1:].lower().split()
            for tok in t:
                if tok in UNITS:
                    unit = tok
                elif tok in ("ri", "ma", "db"):
                    fmt = tok
            continue
        vals.extend(float(x) for x in line.split())
    per = 1 + 2 * nports * nports
    arr = np.array(vals).reshape(-1, per)
    f = arr[:, 0] * UNITS[unit]
    a, b = arr[:, 1::2], arr[:, 2::2]
    if fmt == "ri":
        s = a + 1j * b
    elif fmt == "ma":
        s = a * np.exp(1j * np.radians(b))
    else:
        s = 10 ** (a / 20) * np.exp(1j * np.radians(b))
    S = s.reshape(-1, nports, nports)
    if nports == 2:            # Touchstone v1 2-port order is S11 S21 S12 S22
        S = S.transpose(0, 2, 1)
    return f, S


def write_s1p(path, f_hz, s11, comment: str = ""):
    with open(path, "w") as fh:
        if comment:
            fh.write(f"! {comment}\n")
        fh.write("# HZ S RI R 50\n")
        for f, s in zip(f_hz, s11):
            fh.write(f"{f:.0f} {s.real:.8e} {s.imag:.8e}\n")
