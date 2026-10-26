"""Append-only SHA-256 digest chain (JSON lines).

Every received frame, enrolment step, reference write and decision is chained,
so a later edit, deletion or reordering anywhere in the log breaks every
subsequent hash. This makes the untrusted host's history tamper-evident; it
does not make the host trusted.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

GENESIS = "0" * 64


def _digest(prev: str, body: dict) -> str:
    blob = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(prev.encode() + blob).hexdigest()


class Ledger:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.prev, self.n = GENESIS, 0
        if self.path.exists():
            ok, n, last, err = verify(self.path)
            if not ok:
                raise RuntimeError(f"ledger {self.path} fails verification: {err}")
            self.prev, self.n = last, n

    def append(self, kind: str, payload: dict) -> str:
        body = {"i": self.n, "ts": time.time(), "kind": kind, "payload": payload}
        h = _digest(self.prev, body)
        with open(self.path, "a") as f:
            f.write(json.dumps({**body, "prev": self.prev, "hash": h}, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.prev, self.n = h, self.n + 1
        return h


def verify(path) -> tuple[bool, int, str, str]:
    """Returns (ok, entries, last_hash, error)."""
    prev, n = GENESIS, 0
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            e = json.loads(line)
            body = {k: e[k] for k in ("i", "ts", "kind", "payload")}
            if e["i"] != n:
                return False, n, prev, f"index {e['i']} != {n}"
            if e["prev"] != prev:
                return False, n, prev, f"entry {n}: prev link broken"
            if _digest(prev, body) != e["hash"]:
                return False, n, prev, f"entry {n}: hash mismatch"
            prev, n = e["hash"], n + 1
    return True, n, prev, ""


def sha256_obj(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
