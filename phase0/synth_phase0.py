#!/usr/bin/env python3
"""Rehearsal data for Phase 0: writes synthetic .s1p sweeps + manifest.csv in
the same layout the VNA session should produce, so the analysis can be
dry-run before lab time. Synthetic — not evidence of anything about real vials.

    python3 phase0/synth_phase0.py --out phase0_synth --vials 8 --placements 5 --repeats 3
    python3 phase0/variance_decomp.py phase0_synth/manifest.csv --out phase0_synth/results
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "host"))
sys.path.insert(0, str(HERE))
from pgdd.forward import LIQUIDS, Bench, make_containers, reflection  # noqa: E402
import touchstone  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="phase0_synth")
    ap.add_argument("--vials", type=int, default=8)
    ap.add_argument("--placements", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--points", type=int, default=201)
    ap.add_argument("--placement-sd", type=float, default=0.004)
    ap.add_argument("--noise", type=float, default=0.002, help="complex S11 noise SD")
    ap.add_argument("--same-liquid", action="store_true", help="all vials water: identity = vial only")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)

    rng = np.random.default_rng(a.seed)
    out = Path(a.out)
    (out / "sweeps").mkdir(parents=True, exist_ok=True)
    f = np.linspace(2.3e9, 2.5e9, a.points)
    cons = make_containers(a.vials, rng, ["water"] if a.same_liquid else None)
    rows = []
    for c in cons:
        for p in range(a.placements):
            pk = rng.normal(0, a.placement_sd)
            pph = rng.normal(0, np.radians(0.3))
            for r in range(a.repeats):
                g = reflection(c, f, Bench(), placement_k=pk, placement_ph=pph)
                g = g + rng.normal(0, a.noise, g.shape) + 1j * rng.normal(0, a.noise, g.shape)
                name = f"sweeps/v{c.cid}_p{p}_r{r}.s1p"
                touchstone.write_s1p(out / name, f, g, f"synthetic {c.liquid.name}")
                rows.append({"file": name, "vial": c.cid, "placement": p, "repeat": r})
    with open(out / "manifest.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "vial", "placement", "repeat"])
        w.writeheader(); w.writerows(rows)
    print(f"wrote {len(rows)} sweeps to {out}/sweeps and {out}/manifest.csv")


if __name__ == "__main__":
    main()
