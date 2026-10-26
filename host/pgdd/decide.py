"""Hypothesis evaluation and arbitration.

Hypotheses for a verification session on claimed container c:
    H_c       contents unchanged (own enrolled reference)
    H_k, k!=c contents match another enrolled reference (known substitution)
Acceptance is conditioned jointly on
    (a) lowest robust residual, and
    (b) a quorum of independently validated records supporting the winner,
        spread over enough distinct angles and frequencies.
Without a quorum either way, the decision is INCONCLUSIVE, not a guess.

`residual_only` is the ablation baseline: lowest mean residual + threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .reference import Meas, Reference

CONSISTENT, DRIFT, SUBSTITUTED, INCONCLUSIVE = "CONSISTENT", "DRIFT", "SUBSTITUTED", "INCONCLUSIVE"


@dataclass
class DecideConfig:
    z_max: float = 3.5
    quorum_frac: float = 0.6
    min_angles: int = 3
    min_freqs: int = 5
    min_records: int = 20
    floor_db: float = 0.05
    floor_deg: float = 0.4


@dataclass
class Decision:
    verdict: str
    claimed: int
    matched: int | None
    residual: dict
    support: dict
    n_records: int
    detail: dict = field(default_factory=dict)

    def as_dict(self):
        return self.__dict__


def residual_matrix(meas: list[Meas], refs: dict[int, Reference], cfg: DecideConfig):
    ids = list(refs)
    Z = np.full((len(meas), len(ids)), np.nan)
    for i, m in enumerate(meas):
        for j, h in enumerate(ids):
            z = refs[h].residual(m, cfg.floor_db, cfg.floor_deg)
            if z is not None:
                Z[i, j] = z
    return ids, Z


def arbitrate(claimed: int, meas: list[Meas], refs: dict[int, Reference],
              cfg: DecideConfig = DecideConfig()) -> Decision:
    if claimed not in refs:
        return Decision(INCONCLUSIVE, claimed, None, {}, {}, len(meas), {"why": "no reference for claimed id"})
    ids, Z = residual_matrix(meas, refs, cfg)
    own = ids.index(claimed)
    valid = ~np.isnan(Z[:, own])
    Z, meas_v = Z[valid], [m for m, v in zip(meas, valid) if v]
    n = len(meas_v)
    if n < cfg.min_records:
        return Decision(INCONCLUSIVE, claimed, None, {}, {}, n, {"why": f"{n} usable records < {cfg.min_records}"})

    R = {h: float(np.nanmedian(Z[:, j])) for j, h in enumerate(ids)}
    best = np.nanargmin(np.where(np.isnan(Z), np.inf, Z), axis=1)
    support = {}
    for j, h in enumerate(ids):
        rows = np.where((best == j) & (Z[:, j] <= cfg.z_max))[0]
        support[h] = {"n": int(len(rows)),
                      "angles": len({meas_v[r].angle for r in rows}),
                      "freqs": len({meas_v[r].freq_khz for r in rows})}

    def quorate(s):
        return s["n"] >= cfg.quorum_frac * n and s["angles"] >= cfg.min_angles and s["freqs"] >= cfg.min_freqs

    win = min(R, key=R.get)
    if R[win] <= cfg.z_max and quorate(support[win]):
        v = CONSISTENT if win == claimed else SUBSTITUTED
        return Decision(v, claimed, win, R, support, n)

    drift_rows = np.where(Z[:, own] > cfg.z_max)[0]
    ds = {"n": int(len(drift_rows)), "angles": len({meas_v[r].angle for r in drift_rows}),
          "freqs": len({meas_v[r].freq_khz for r in drift_rows})}
    if quorate(ds):
        return Decision(DRIFT, claimed, None, R, support, n, {"drift_support": ds})
    return Decision(INCONCLUSIVE, claimed, None, R, support, n, {"drift_support": ds})


def residual_only(claimed: int, meas: list[Meas], refs: dict[int, Reference],
                  cfg: DecideConfig = DecideConfig()) -> Decision:
    ids, Z = residual_matrix(meas, refs, cfg)
    R = {h: float(np.nanmean(Z[:, j])) for j, h in enumerate(ids) if np.any(~np.isnan(Z[:, j]))}
    if not R:
        return Decision(DRIFT, claimed, None, {}, {}, len(meas))
    win = min(R, key=R.get)
    if R[win] <= cfg.z_max:
        return Decision(CONSISTENT if win == claimed else SUBSTITUTED, claimed, win, R, {}, len(meas))
    return Decision(DRIFT, claimed, None, R, {}, len(meas))
