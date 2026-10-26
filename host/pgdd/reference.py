"""Per-container reference store and reference subtraction.

A reference can only be written with a CorroborationCertificate issued by
enrollment.bootstrap_enrol(). Writes are versioned and append-only; each one
is chained into the ledger after the enrolment steps that justified it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .calib import DEFAULT_CAL, features
from .ledger import Ledger, sha256_obj


@dataclass(frozen=True)
class Meas:
    angle: int
    freq_khz: int
    amp: float
    ph: float
    commit_idx: int = -1
    temp_c: float | None = None


def to_meas(records, cal=DEFAULT_CAL) -> list[Meas]:
    out = []
    for r in records:
        a, p = features(r, cal)
        out.append(Meas(r.angle_idx, r.freq_khz, a, p, r.commit_idx, r.temp_c))
    return out


@dataclass
class Reference:
    container_id: int
    freqs: dict          # freq_khz -> {"mu_a","sd_a","mu_p","sd_p","n"}
    angles_used: list
    excluded_freqs: list
    meta: dict

    def to_json(self) -> dict:
        return {"container_id": self.container_id,
                "freqs": {str(k): v for k, v in sorted(self.freqs.items())},
                "angles_used": self.angles_used, "excluded_freqs": self.excluded_freqs,
                "meta": self.meta}

    @staticmethod
    def from_json(d: dict) -> "Reference":
        return Reference(d["container_id"], {int(k): v for k, v in d["freqs"].items()},
                         d["angles_used"], d["excluded_freqs"], d["meta"])

    def residual(self, m: Meas, floor_db: float, floor_deg: float) -> float | None:
        """Per-record z-residual (max over amplitude and phase). None if the
        frequency is not usable in this reference."""
        e = self.freqs.get(m.freq_khz)
        if e is None:
            return None
        sa = np.hypot(e["sd_a"], floor_db)
        sp = np.hypot(e["sd_p"], floor_deg)
        return float(max(abs(m.amp - e["mu_a"]) / sa, abs(m.ph - e["mu_p"]) / sp))


class ReferenceStore:
    def __init__(self, root, ledger: Ledger):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger

    def _versions(self, cid: int) -> list[Path]:
        return sorted(self.root.glob(f"ref_{cid}_v*.json"), key=lambda p: int(p.stem.split("_v")[-1]))

    def write(self, cert) -> Path:
        from .enrollment import CorroborationCertificate
        if not isinstance(cert, CorroborationCertificate) or not cert.ok:
            raise PermissionError("reference write requires a passing corroboration certificate")
        ref = cert.reference
        body = ref.to_json()
        if sha256_obj(body) != cert.reference_digest:
            raise PermissionError("reference does not match its certificate")
        n = len(self._versions(ref.container_id)) + 1
        p = self.root / f"ref_{ref.container_id}_v{n}.json"
        if p.exists():
            raise FileExistsError(p)
        p.write_text(json.dumps({"reference": body, "certificate": cert.summary()}, indent=1))
        self.ledger.append("reference_write", {"container_id": ref.container_id, "version": n,
                                               "reference_sha256": cert.reference_digest,
                                               "certificate_sha256": sha256_obj(cert.summary())})
        return p

    def latest(self, cid: int) -> Reference | None:
        v = self._versions(cid)
        return Reference.from_json(json.loads(v[-1].read_text())["reference"]) if v else None

    def all_latest(self) -> dict[int, Reference]:
        ids = {int(p.stem.split("_")[1]) for p in self.root.glob("ref_*_v*.json")}
        return {i: self.latest(i) for i in sorted(ids)}
