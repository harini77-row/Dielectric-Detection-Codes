#!/usr/bin/env python3
"""Phase 0: decompose VNA S11 variance into vial identity vs placement vs noise.

Design (balanced, nested): V vials x P placements (cradle re-seats / angles)
x R repeats (sweeps without touching anything). Manifest CSV columns:
    file,vial,placement,repeat
with `file` a .s1p/.s2p path relative to the manifest.

Per frequency, for amplitude_db = 20 log10|S11| and phase_deg = angle(S11):
    MS_vial, MS_place(vial), MS_rep   (nested ANOVA mean squares)
    s2_noise = MS_rep
    s2_place = max(0, (MS_place - MS_rep) / R)
    s2_vial  = max(0, (MS_vial - MS_place) / (P R))
    ICC_vial = s2_vial / (s2_vial + s2_place + s2_noise)
plus the S11-minimum frequency per sweep, decomposed the same way (MHz),
which is what decides whether the AD8302 chain can see the difference.

Outputs: <out>/variance_by_freq.csv, <out>/summary.txt, <out>/icc_vs_freq.png

Gate for continuing to hardware (defaults, adjust before the VNA session):
    median ICC_vial over the band >= 0.5, and
    vial-to-vial SD exceeds 3 x (placement+noise) SD on >= 50 % of points.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import numpy as np

try:
    from . import touchstone
except ImportError:  # run as a script
    import touchstone  # type: ignore

# Resolution of the cheap chain, for the visibility check (datasheet-level,
# replace with measured values from build stage 2).
AD8302_RES_DB = 0.1
AD8302_RES_DEG = 0.5


def nested_anova(Y: np.ndarray):
    """Y[V, P, R, ...] -> dict of variance components over trailing axes."""
    V, P, R = Y.shape[:3]
    gm = Y.mean(axis=(0, 1, 2))
    vm = Y.mean(axis=(1, 2))
    pm = Y.mean(axis=2)
    ss_v = P * R * ((vm - gm) ** 2).sum(axis=0)
    ss_p = R * ((pm - vm[:, None]) ** 2).sum(axis=(0, 1))
    ss_r = ((Y - pm[:, :, None]) ** 2).sum(axis=(0, 1, 2))
    ms_v = ss_v / (V - 1)
    ms_p = ss_p / (V * (P - 1))
    ms_r = ss_r / (V * P * (R - 1))
    s2n = ms_r
    s2p = np.maximum(0.0, (ms_p - ms_r) / R)
    s2v = np.maximum(0.0, (ms_v - ms_p) / (P * R))
    tot = s2v + s2p + s2n
    icc = np.where(tot > 0, s2v / np.where(tot > 0, tot, 1), np.nan)
    return {"ms_vial": ms_v, "ms_place": ms_p, "ms_rep": ms_r,
            "s2_vial": s2v, "s2_place": s2p, "s2_noise": s2n, "icc_vial": icc}


def load(manifest: Path):
    rows = list(csv.DictReader(open(manifest)))
    vials = sorted({r["vial"] for r in rows})
    places = sorted({r["placement"] for r in rows})
    reps = sorted({r["repeat"] for r in rows})
    cells = defaultdict(list)
    for r in rows:
        cells[(r["vial"], r["placement"], r["repeat"])].append(r["file"])
    missing = [(v, p, k) for v in vials for p in places for k in reps if (v, p, k) not in cells]
    if missing:
        raise SystemExit(f"design not balanced, missing cells e.g. {missing[:3]}")
    f0 = None
    S = None
    for i, v in enumerate(vials):
        for j, p in enumerate(places):
            for k, rep in enumerate(reps):
                f, s = touchstone.read(manifest.parent / cells[(v, p, rep)][0])
                if f0 is None:
                    f0 = f
                    S = np.zeros((len(vials), len(places), len(reps), len(f)), complex)
                elif len(f) != len(f0) or not np.allclose(f, f0):
                    raise SystemExit("all sweeps must share one frequency grid")
                S[i, j, k] = s[:, 0, 0]
    return vials, places, reps, f0, S


def analyse(manifest, out, band=None, icc_gate=0.5, sep_gate=0.5):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    vials, places, reps, f, S = load(Path(manifest))
    if band:
        m = (f >= band[0]) & (f <= band[1])
        f, S = f[m], S[..., m]
    amp = 20 * np.log10(np.abs(S))
    ph = np.degrees(np.unwrap(np.angle(S), axis=-1))
    A, Pp = nested_anova(amp), nested_anova(ph)
    fmin = f[np.argmin(np.abs(S), axis=-1)] / 1e6        # MHz, per sweep
    Fm = nested_anova(fmin[..., None])

    with open(out / "variance_by_freq.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_hz", "amp_s2_vial", "amp_s2_place", "amp_s2_noise", "amp_icc_vial",
                    "ph_s2_vial", "ph_s2_place", "ph_s2_noise", "ph_icc_vial"])
        for i in range(len(f)):
            w.writerow([f"{f[i]:.0f}"] + [f"{A[k][i]:.6g}" for k in ("s2_vial", "s2_place", "s2_noise", "icc_vial")]
                       + [f"{Pp[k][i]:.6g}" for k in ("s2_vial", "s2_place", "s2_noise", "icc_vial")])

    def sep(D):
        return float(np.mean(np.sqrt(D["s2_vial"]) > 3 * np.sqrt(D["s2_place"] + D["s2_noise"])))

    lines = [
        f"design: {len(vials)} vials x {len(places)} placements x {len(reps)} repeats, "
        f"{len(f)} points {f[0]/1e9:.3f}-{f[-1]/1e9:.3f} GHz",
        f"amplitude: median ICC_vial {np.nanmedian(A['icc_vial']):.3f}; "
        f"vial SD > 3x(place+noise) SD on {100*sep(A):.0f}% of points",
        f"           median SD vial/place/noise = {np.median(np.sqrt(A['s2_vial'])):.4f} / "
        f"{np.median(np.sqrt(A['s2_place'])):.4f} / {np.median(np.sqrt(A['s2_noise'])):.4f} dB",
        f"phase:     median ICC_vial {np.nanmedian(Pp['icc_vial']):.3f}; "
        f"vial SD > 3x(place+noise) SD on {100*sep(Pp):.0f}% of points",
        f"           median SD vial/place/noise = {np.median(np.sqrt(Pp['s2_vial'])):.3f} / "
        f"{np.median(np.sqrt(Pp['s2_place'])):.3f} / {np.median(np.sqrt(Pp['s2_noise'])):.3f} deg",
        f"S11-minimum frequency: SD vial/place/noise = {np.sqrt(Fm['s2_vial'][0]):.3f} / "
        f"{np.sqrt(Fm['s2_place'][0]):.3f} / {np.sqrt(Fm['s2_noise'][0]):.3f} MHz "
        f"(VNA step {(f[1]-f[0])/1e6:.3f} MHz)",
        f"AD8302 visibility: placement+noise SD vs chain resolution — amplitude "
        f"{np.median(np.sqrt(A['s2_place']+A['s2_noise'])):.3f} dB vs {AD8302_RES_DB} dB, phase "
        f"{np.median(np.sqrt(Pp['s2_place']+Pp['s2_noise'])):.2f} deg vs {AD8302_RES_DEG} deg",
    ]
    ok = (np.nanmedian(A["icc_vial"]) >= icc_gate or np.nanmedian(Pp["icc_vial"]) >= icc_gate) and \
         max(sep(A), sep(Pp)) >= sep_gate
    lines.append(f"PHASE 0 GATE: {'PASS' if ok else 'FAIL'} "
                 f"(ICC >= {icc_gate} and separable on >= {100*sep_gate:.0f}% of points, either feature)")
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(2, 1, figsize=(6.4, 5.2), sharex=True)
        ax[0].plot(f / 1e9, A["icc_vial"], label="amplitude")
        ax[0].plot(f / 1e9, Pp["icc_vial"], label="phase")
        ax[0].axhline(icc_gate, ls="--", lw=0.8, color="grey")
        ax[0].set_ylabel("ICC (vial identity)"); ax[0].set_ylim(0, 1.02); ax[0].legend(fontsize=8)
        for k, lab in (("s2_vial", "vial"), ("s2_place", "placement"), ("s2_noise", "noise")):
            ax[1].semilogy(f / 1e9, np.sqrt(A[k]) + 1e-9, label=lab)
        ax[1].set_ylabel("amplitude SD (dB)"); ax[1].set_xlabel("frequency (GHz)"); ax[1].legend(fontsize=8)
        for a in ax: a.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(out / "icc_vs_freq.png", dpi=150); plt.close(fig)
    except Exception as e:  # plotting is optional
        print("plot skipped:", e)
    return ok, A, Pp, Fm


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest")
    ap.add_argument("--out", default="phase0_out")
    ap.add_argument("--band", nargs=2, type=float, metavar=("F_LO_HZ", "F_HI_HZ"))
    a = ap.parse_args(argv)
    ok, *_ = analyse(a.manifest, a.out, a.band)
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
