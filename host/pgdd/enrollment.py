"""Bootstrap-verified enrolment.

The reference for a container is written only after the enrolment records
corroborate each other across differing angle/frequency pairings:

  1. frequency stability  - a frequency is usable only if its spread across
                            angles is small (rejects e.g. a steady interferer)
  2. angle corroboration  - each angle must agree with the leave-one-out mean
                            of the others on most usable frequencies (rejects a
                            mis-seated vial at one detent); two passes
  3. split-half cross-check - a reference built from one half of the
                            corroborated angles must explain the other half,
                            and vice versa
  4. sufficiency          - enough angles and frequencies survive

Every step is written to the ledger *before* the certificate is issued, so the
log shows reference_write only ever follows a passing chain of checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .ledger import Ledger, sha256_obj
from .reference import Meas, Reference


@dataclass
class EnrolConfig:
    min_angles: int = 4
    min_freq_frac: float = 0.8
    max_spread_db: float = 0.6          # set from Phase 0 placement variance
    max_spread_deg: float = 4.0
    z_max: float = 3.5
    outlier_frac: float = 0.25          # angle rejected if > this frac of freqs disagree
    z_cross: float = 2.0                # median split-half z must be below this
    floor_db: float = 0.05              # detector/noise floor added to sigma
    floor_deg: float = 0.4


@dataclass
class CorroborationCertificate:
    ok: bool
    container_id: int
    reason: str
    reference: Reference | None
    reference_digest: str
    steps: list = field(default_factory=list)

    def summary(self) -> dict:
        return {"ok": self.ok, "container_id": self.container_id, "reason": self.reason,
                "reference_sha256": self.reference_digest, "steps": self.steps}


def _matrix(meas: list[Meas]):
    angles = sorted({m.angle for m in meas})
    freqs = sorted({m.freq_khz for m in meas})
    ai = {a: i for i, a in enumerate(angles)}
    fi = {f: i for i, f in enumerate(freqs)}
    A = np.full((len(angles), len(freqs)), np.nan)
    P = np.full_like(A, np.nan)
    for m in meas:
        A[ai[m.angle], fi[m.freq_khz]] = m.amp
        P[ai[m.angle], fi[m.freq_khz]] = m.ph
    return angles, freqs, A, P


def _mad(x, axis=0):
    med = np.nanmedian(x, axis=axis)
    return 1.4826 * np.nanmedian(np.abs(x - med), axis=axis)


def _z(A, P, rows_ref, rows_test, fmask, cfg):
    mu_a = np.nanmean(A[rows_ref][:, fmask], axis=0)
    mu_p = np.nanmean(P[rows_ref][:, fmask], axis=0)
    sd_a = np.nanstd(A[rows_ref][:, fmask], axis=0, ddof=1) if len(rows_ref) > 1 else 0 * mu_a
    sd_p = np.nanstd(P[rows_ref][:, fmask], axis=0, ddof=1) if len(rows_ref) > 1 else 0 * mu_p
    za = np.abs(A[rows_test][:, fmask] - mu_a) / np.hypot(sd_a, cfg.floor_db)
    zp = np.abs(P[rows_test][:, fmask] - mu_p) / np.hypot(sd_p, cfg.floor_deg)
    return np.fmax(za, zp)


def bootstrap_enrol(container_id: int, meas: list[Meas], ledger: Ledger,
                    cfg: EnrolConfig = EnrolConfig(), session_meta: dict | None = None
                    ) -> CorroborationCertificate:
    steps = []

    def log(step, **kw):
        e = {"step": step, **kw}
        steps.append(e)
        ledger.append("enrol_step", {"container_id": container_id, **e})

    def fail(reason):
        log("refused", reason=reason)
        return CorroborationCertificate(False, container_id, reason, None, "", steps)

    angles, freqs, A, P = _matrix(meas)
    log("collected", n_records=len(meas), angles=angles, n_freqs=len(freqs),
        commit_idx=[m.commit_idx for m in meas][:4096])
    if len(angles) < cfg.min_angles:
        return fail(f"only {len(angles)} angles (< {cfg.min_angles})")

    # 1. frequency stability
    n_present = np.sum(~np.isnan(A), axis=0)
    spread_a, spread_p = _mad(A), _mad(P)
    fmask = (n_present >= cfg.min_angles) & (spread_a <= cfg.max_spread_db) & (spread_p <= cfg.max_spread_deg)
    excluded = [freqs[i] for i in np.where(~fmask)[0]]
    log("frequency_stability", usable=int(fmask.sum()), total=len(freqs), excluded=excluded,
        worst_spread_db=float(np.nanmax(spread_a)), worst_spread_deg=float(np.nanmax(spread_p)))
    if fmask.mean() < cfg.min_freq_frac:
        return fail(f"only {fmask.sum()}/{len(freqs)} frequencies stable across angles")

    # 2. angle corroboration (leave-one-out, two passes)
    keep = list(range(len(angles)))
    for pas in (1, 2):
        bad = []
        for i in keep:
            others = [j for j in keep if j != i]
            z = _z(A, P, others, [i], fmask, cfg)[0]
            frac = float(np.nanmean(z > cfg.z_max))
            if frac > cfg.outlier_frac:
                bad.append((angles[i], round(frac, 3)))
        log("angle_corroboration", pass_=pas, rejected=bad, kept=[angles[i] for i in keep if angles[i] not in dict(bad)])
        keep = [i for i in keep if angles[i] not in dict(bad)]
        if not bad:
            break
    if len(keep) < cfg.min_angles:
        return fail(f"only {len(keep)} angles corroborate (< {cfg.min_angles})")

    # 3. split-half cross-check over different angle subsets
    g1, g2 = keep[0::2], keep[1::2]
    z12 = float(np.nanmedian(_z(A, P, g1, g2, fmask, cfg)))
    z21 = float(np.nanmedian(_z(A, P, g2, g1, fmask, cfg)))
    log("split_half", group1=[angles[i] for i in g1], group2=[angles[i] for i in g2],
        median_z_1to2=round(z12, 3), median_z_2to1=round(z21, 3))
    if max(z12, z21) > cfg.z_cross:
        return fail(f"split halves disagree (median z {max(z12, z21):.2f} > {cfg.z_cross})")

    # 4. build reference from corroborated angles and usable freqs only
    fr = {}
    for k, f in enumerate(freqs):
        if not fmask[k]:
            continue
        a = A[keep, k]; p = P[keep, k]
        fr[f] = {"mu_a": float(np.nanmean(a)), "sd_a": float(np.nanstd(a, ddof=1)),
                 "mu_p": float(np.nanmean(p)), "sd_p": float(np.nanstd(p, ddof=1)),
                 "n": int(np.sum(~np.isnan(a)))}
    temps = [m.temp_c for m in meas if m.temp_c is not None]
    ref = Reference(container_id, fr, [angles[i] for i in keep], excluded,
                    {**(session_meta or {}), "enrol_temp_c": float(np.mean(temps)) if temps else None,
                     "config": cfg.__dict__})
    digest = sha256_obj(ref.to_json())
    log("certified", angles_used=ref.angles_used, n_freqs=len(fr), reference_sha256=digest)
    return CorroborationCertificate(True, container_id, "corroborated", ref, digest, steps)
