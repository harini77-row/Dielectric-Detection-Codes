"""Untrusted-domain orchestration on the Pi 5: receive committed records,
store + chain them, enrol (bootstrap-verified) and verify (arbitrated)."""
from __future__ import annotations

import time
from pathlib import Path

from .decide import DecideConfig, arbitrate
from .enrollment import EnrolConfig, bootstrap_enrol
from .ledger import Ledger
from .link import HostLink
from .record import MODE_ENROL, MODE_VERIFY
from .reference import ReferenceStore, to_meas
from .store import Store


class Host:
    def __init__(self, root, transport, enrol_cfg: EnrolConfig = EnrolConfig(),
                 decide_cfg: DecideConfig = DecideConfig()):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.root / "ledger.jsonl")
        self.store = Store(self.root)
        self.refs = ReferenceStore(self.root / "refs", self.ledger)
        self.enrol_cfg, self.decide_cfg = enrol_cfg, decide_cfg
        hw = not hasattr(transport, "ring")         # SimPico has a ring; real SPI does not
        self.link = HostLink(transport, on_record=self._on_record, poll_s=0.001 if hw else 0.0)
        self._sid_path = self.root / "session_counter"

    def _on_record(self, r, raw: bytes):
        t = time.time()
        self.store.add(r, t)
        self.ledger.append("record", {"frame": raw.hex(), "host_rx_time": t,
                                      "boot_id": r.boot_id, "commit_idx": r.commit_idx})

    def _next_sid(self) -> int:
        n = int(self._sid_path.read_text()) + 1 if self._sid_path.exists() else 1
        self._sid_path.write_text(str(n))
        return n & 0xFFFF

    def _session(self, cid, mode, plan_id, n_angles):
        sid = self._next_sid()
        self.ledger.append("session_start", {"container_id": cid, "session_id": sid, "mode": mode,
                                             "plan_id": plan_id, "n_angles": n_angles})
        recs = self.link.run_session(cid, sid, mode, plan_id, n_angles)
        self.ledger.append("session_end", {"session_id": sid, "n_records": len(recs),
                                           "link": self.link.stats.__dict__})
        return sid, recs

    def enrol(self, cid: int, n_angles: int = 8, plan_id: int = 0):
        sid, recs = self._session(cid, MODE_ENROL, plan_id, n_angles)
        cert = bootstrap_enrol(cid, to_meas(recs), self.ledger, self.enrol_cfg,
                               {"session_id": sid, "boot_id": self.link.boot_id, "plan_id": plan_id})
        path = self.refs.write(cert) if cert.ok else None
        return cert, path

    def verify(self, cid: int, n_angles: int = 8, plan_id: int = 0):
        sid, recs = self._session(cid, MODE_VERIFY, plan_id, n_angles)
        d = arbitrate(cid, to_meas(recs), self.refs.all_latest(), self.decide_cfg)
        self.ledger.append("decision", {"session_id": sid, "boot_id": self.link.boot_id,
                                        "commit_idx": [r.commit_idx for r in recs],
                                        **{k: v for k, v in d.as_dict().items()}})
        return d
