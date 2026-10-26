"""Quorum+residual vs residual-only arbitration under injected faults.

Every verification session goes through the full path (SimPico -> gate model
-> 64-byte frames -> HostLink -> features -> arbitration), and both methods
are scored on the *same* records (paired comparison).

IMPORTANT: these figures characterise the synthetic corruption generator and
the forward model in pgdd.forward. They are not measured system performance.
"""
from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import numpy as np

from .decide import CONSISTENT, DRIFT, INCONCLUSIVE, SUBSTITUTED, DecideConfig, arbitrate, residual_only
from .enrollment import EnrolConfig, bootstrap_enrol
from .forward import LIQUIDS, make_containers
from .link import HostLink
from .record import MODE_ENROL, MODE_VERIFY
from .reference import to_meas
from .sim import Faults, SimPico

DISCLAIMER = ("Synthetic: results describe the corruption generator and forward model, "
              "not measured system performance.")

FAULT_MODES = ("placement_slip", "rf_interference", "temperature", "transient_glitch", "pll_unlock")


class NullLedger:
    def append(self, *a, **k):
        return ""


def faults_for(mode: str, rate: float, n_angles: int, rng) -> Faults:
    if mode == "placement_slip":
        k = int(round(rate * n_angles))
        return Faults(slip_angles=tuple(rng.choice(n_angles, k, replace=False)) if k else ())
    if mode == "rf_interference":
        return Faults(interf_band_khz=(2400000, 2480000), interf_rate=min(1.0, 2 * rate))
    if mode == "temperature":
        return Faults(temp_offset_c=20 * rate)
    if mode == "transient_glitch":
        return Faults(glitch_rate=rate)
    if mode == "pll_unlock":
        return Faults(unlock_rate=rate)
    if mode == "none":
        return Faults()
    raise ValueError(mode)


def _session(pico, link, cid, sid, mode, n_angles, plan):
    return link.run_session(cid, sid, mode, plan, n_angles)


def run_seed(seed: int, rates, modes, n_containers=6, n_angles=8, plan=0,
             ecfg=EnrolConfig(), dcfg=DecideConfig(), gate: bool = True):
    rng = np.random.default_rng(seed)
    pico = SimPico(seed)
    link = HostLink(pico)
    cons = make_containers(n_containers, rng)
    sid = 0
    refs = {}
    for c in cons:                                # clean enrolment
        pico.state.mounted, pico.state.faults = c, Faults()
        sid += 1
        recs = _session(pico, link, c.cid, sid, MODE_ENROL, n_angles, plan)
        cert = bootstrap_enrol(c.cid, to_meas(recs), NullLedger(), ecfg)
        if cert.ok:
            refs[c.cid] = cert.reference
    rows = []
    liquids = list(LIQUIDS.values())
    for mode in modes:
        for rate in rates:
            for c in cons:
                if c.cid not in refs:
                    continue
                for truth in ("unchanged", "substituted"):
                    if truth == "unchanged":
                        actual = c
                    else:
                        others = [l for l in liquids if l.name != c.liquid.name]
                        actual = c.substituted(others[int(rng.integers(len(others)))])
                    pico.state.mounted = actual
                    pico.state.faults = faults_for(mode, rate, n_angles, rng)
                    pico.gate_enabled = gate          # enrolment above always gated
                    sid += 1
                    recs = _session(pico, link, c.cid, sid, MODE_VERIFY, n_angles, plan)
                    meas = to_meas(recs)
                    for method, fn in (("quorum+residual", arbitrate), ("residual-only", residual_only)):
                        d = fn(c.cid, meas, refs, dcfg)
                        label = method if gate else method + " [gate off]"
                        rows.append({"seed": seed, "mode": mode, "rate": rate, "method": label,
                                     "truth": truth, "verdict": d.verdict, "n_records": len(recs)})
    return rows


def summarise(rows):
    """Per (mode, rate, method): mean +- SD over seeds of false-accept,
    false-alarm and inconclusive rates."""
    from collections import defaultdict
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[(r["mode"], r["rate"], r["method"])][r["seed"]].append(r)
    out = []
    for (mode, rate, method), seeds in sorted(by.items()):
        fa, fl, inc, acc = [], [], [], []
        for _, rs in seeds.items():
            ch = [r for r in rs if r["truth"] == "substituted"]
            un = [r for r in rs if r["truth"] == "unchanged"]
            fa.append(np.mean([r["verdict"] == CONSISTENT for r in ch]) if ch else np.nan)
            fl.append(np.mean([r["verdict"] in (DRIFT, SUBSTITUTED) for r in un]) if un else np.nan)
            inc.append(np.mean([r["verdict"] == INCONCLUSIVE for r in rs]))
            acc.append(np.mean([(r["truth"] == "unchanged") == (r["verdict"] == CONSISTENT)
                                and r["verdict"] != INCONCLUSIVE for r in rs]))
        f = lambda v: (float(np.nanmean(v)), float(np.nanstd(v, ddof=1)) if len(v) > 1 else 0.0)
        out.append({"mode": mode, "rate": rate, "method": method,
                    "false_accept": f(fa), "false_alarm": f(fl), "inconclusive": f(inc), "correct": f(acc)})
    return out


def confusion(rows, mode, rate, method):
    cols = [CONSISTENT, DRIFT, SUBSTITUTED, INCONCLUSIVE]
    m = {t: {c: 0 for c in cols} for t in ("unchanged", "substituted")}
    for r in rows:
        if r["mode"] == mode and r["rate"] == rate and r["method"] == method:
            m[r["truth"]][r["verdict"]] += 1
    return m


def run(out_dir, seeds=5, rates=(0.0, 0.1, 0.2, 0.3), modes=FAULT_MODES, n_containers=6, plot=True,
        gate_off_too=True):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in range(seeds):
        rows += run_seed(s, rates, modes, n_containers)
        if gate_off_too:
            rows += run_seed(s, rates, modes, n_containers, gate=False)
    with open(out / "ablation_raw.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    summ = summarise(rows)
    with open(out / "ablation_summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "rate", "method", "false_accept_mean", "false_accept_sd", "false_alarm_mean",
                    "false_alarm_sd", "inconclusive_mean", "inconclusive_sd", "correct_mean", "correct_sd"])
        for s in summ:
            w.writerow([s["mode"], s["rate"], s["method"], *s["false_accept"], *s["false_alarm"],
                        *s["inconclusive"], *s["correct"]])
    if plot:
        _plot(summ, out / "ablation.png", modes, rates)
    return rows, summ


def _plot(summ, path, modes, rates):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, len(modes), figsize=(3.2 * len(modes), 3.2), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, mode in zip(axes, modes):
        for method, ls in (("quorum+residual", "-"), ("residual-only", "--"),
                           ("quorum+residual [gate off]", ":"), ("residual-only [gate off]", "-.")):
            pts = [s for s in summ if s["mode"] == mode and s["method"] == method]
            if not pts:
                continue
            x = [p["rate"] for p in pts]
            y = [p["correct"][0] for p in pts]
            e = [p["correct"][1] for p in pts]
            ax.errorbar(x, y, yerr=e, ls=ls, marker="o", ms=3, capsize=2, label=method)
        ax.set_title(mode.replace("_", " "), fontsize=9)
        ax.set_xlabel("corruption rate")
        ax.set_ylim(-0.02, 1.02)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("correct decision rate (mean ± SD over seeds)")
    axes[0].legend(fontsize=7)
    fig.suptitle(DISCLAIMER, fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
