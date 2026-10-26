"""pytest -q host/tests"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from pgdd import gate_model
from pgdd.decide import CONSISTENT, DRIFT, INCONCLUSIVE, SUBSTITUTED, arbitrate
from pgdd.enrollment import CorroborationCertificate, EnrolConfig, bootstrap_enrol
from pgdd.forward import LIQUIDS, make_containers
from pgdd.ledger import Ledger, verify
from pgdd.link import HostLink
from pgdd.record import (REC_COMMITTED, FrameError, Record, Status, make_record, pack_cmd,
                         pack_status, parse_cmd, parse_frame, MODE_ENROL, MODE_VERIFY)
from pgdd.reference import ReferenceStore, to_meas
from pgdd.sim import Faults, SimPico

ROOT = Path(__file__).resolve().parents[2]


class NullLedger:
    def append(self, *a, **k):
        return ""


# ------------------------------------------------------------------ wire format
def committed(rec: Record) -> bytes:
    b = bytearray(rec.pack())
    b[0:4] = REC_COMMITTED.to_bytes(4, "little")
    return bytes(b)


def test_record_roundtrip_and_crc():
    r = make_record(seq=7, container_id=101, freq_khz=2400000, vmag_a=14400, vphs_a=8000,
                    vmag_b=14410, vphs_b=8003, commit_idx=3, boot_id=0xABCDEF01)
    fr = parse_frame(committed(r))
    assert isinstance(fr, Record) and fr.seq == 7 and fr.commit_idx == 3
    bad = bytearray(committed(r)); bad[40] ^= 1
    with pytest.raises(FrameError):
        parse_frame(bytes(bad))


def test_uncommitted_record_is_refused():
    r = make_record(seq=1)
    with pytest.raises(FrameError):
        parse_frame(r.pack())           # commit word 0: CPU-built, never admitted


def test_status_and_cmd_frames():
    s = parse_frame(pack_status(5, 10, 1, 2, 9))
    assert isinstance(s, Status) and s.head == 10 and s.session_id == 9
    c = parse_cmd(pack_cmd(cmd=1, mode=2, plan_id=0, n_angles=8, container_id=42, session_id=3, ack=17, nack=True))
    assert c["container_id"] == 42 and c["ack"] == 17 and c["nack"] == 1


# ------------------------------------------------------------------ gate
def test_gate_dual_grid_guarantees():
    rng = np.random.default_rng(0)
    for _ in range(20000):
        m, p = int(rng.integers(5000, 30000)), int(rng.integers(0, 30000))
        dm, dp = int(rng.integers(-200, 200)), int(rng.integers(-200, 200))
        ok = gate_model.admit(m, m + dm, p, p + dp)
        if abs(dm) < 32 and abs(dp) < 32:
            assert ok
        if abs(dm) >= 64 or abs(dp) >= 64:
            assert not ok
    assert not gate_model.admit(1000, 1000, 2000, 2000, poison=True)


def test_pio_program_matches_model():
    out = subprocess.run([sys.executable, str(ROOT / "tools/pio_emu.py"), "--n", "20000"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


# ------------------------------------------------------------------ link
def _setup(seed=0, faults=Faults()):
    pico = SimPico(seed)
    c = make_containers(1, np.random.default_rng(seed))[0]
    pico.state.mounted, pico.state.faults = c, faults
    return pico, HostLink(pico), c


def test_rejected_records_never_reach_host():
    pico, link, c = _setup(faults=Faults(glitch_rate=0.4, unlock_rate=0.1))
    recs = link.run_session(c.cid, 1, MODE_VERIFY, 0, 8)
    assert pico.stats["rejected"] > 0
    assert len(recs) == pico.stats["committed"]
    # interior seq gaps are the only trace of rejects the host can see
    attempts = 21 * 8
    assert recs[0].seq + link.stats.seq_gaps + (attempts - 1 - recs[-1].seq) == pico.stats["rejected"]
    for r in recs:
        assert gate_model.admit(r.vmag_a, r.vmag_b, r.vphs_a, r.vphs_b)
    assert [r.commit_idx for r in recs] == list(range(len(recs)))


def test_link_recovers_from_bit_errors_and_backpressure():
    pico, link, c = _setup(faults=Faults(link_error_rate=0.1))
    recs = link.run_session(c.cid, 1, MODE_ENROL, 1, 12)     # 41 x 12 = 492 > ring of 64
    assert len(recs) == 41 * 12 == pico.stats["committed"]
    assert link.stats.crc_errors > 0
    assert len({r.commit_idx for r in recs}) == len(recs)


# ------------------------------------------------------------------ ledger
def test_ledger_tamper_detected(tmp_path):
    lg = Ledger(tmp_path / "l.jsonl")
    for i in range(5):
        lg.append("x", {"i": i})
    assert verify(tmp_path / "l.jsonl")[0]
    lines = (tmp_path / "l.jsonl").read_text().splitlines()
    e = json.loads(lines[2]); e["payload"]["i"] = 99; lines[2] = json.dumps(e)
    (tmp_path / "l.jsonl").write_text("\n".join(lines) + "\n")
    ok, n, _, err = verify(tmp_path / "l.jsonl")
    assert not ok and n == 2
    with pytest.raises(RuntimeError):
        Ledger(tmp_path / "l.jsonl")


# ------------------------------------------------------------------ enrolment
def _enrol_meas(seed, faults):
    pico, link, c = _setup(seed, faults)
    return c, to_meas(link.run_session(c.cid, 1, MODE_ENROL, 0, 8))


def test_enrolment_excludes_misseated_angle():
    c, meas = _enrol_meas(1, Faults(slip_angles=(5,), slip_k=0.08))
    cert = bootstrap_enrol(c.cid, meas, NullLedger())
    assert cert.ok and 5 not in cert.reference.angles_used


def test_enrolment_refused_when_views_do_not_corroborate():
    c, meas = _enrol_meas(2, Faults(slip_angles=(1, 3, 5, 6, 7), slip_k=0.08))
    cert = bootstrap_enrol(c.cid, meas, NullLedger())
    assert not cert.ok


def test_reference_write_requires_certificate(tmp_path):
    lg = Ledger(tmp_path / "l.jsonl")
    store = ReferenceStore(tmp_path / "refs", lg)
    c, meas = _enrol_meas(3, Faults())
    cert = bootstrap_enrol(c.cid, meas, lg)
    assert cert.ok
    with pytest.raises(PermissionError):
        store.write(CorroborationCertificate(False, c.cid, "x", cert.reference, cert.reference_digest))
    forged = CorroborationCertificate(True, c.cid, "x", cert.reference, "0" * 64)
    with pytest.raises(PermissionError):
        store.write(forged)
    store.write(cert)
    kinds = [json.loads(l)["kind"] for l in (tmp_path / "l.jsonl").read_text().splitlines()]
    assert kinds.index("reference_write") > max(i for i, k in enumerate(kinds) if k == "enrol_step")


# ------------------------------------------------------------------ arbitration
def test_arbitration_end_to_end():
    rng = np.random.default_rng(4)
    pico = SimPico(4)
    link = HostLink(pico)
    cons = make_containers(3, rng)
    refs, sid = {}, 0
    for c in cons:
        pico.state.mounted = c; sid += 1
        refs[c.cid] = bootstrap_enrol(c.cid, to_meas(link.run_session(c.cid, sid, MODE_ENROL, 0, 8)),
                                      NullLedger()).reference

    def verdict(actual, claimed, faults=Faults()):
        nonlocal sid
        pico.state.mounted, pico.state.faults = actual, faults; sid += 1
        return arbitrate(claimed, to_meas(link.run_session(claimed, sid, MODE_VERIFY, 0, 8)), refs)

    assert verdict(cons[0], cons[0].cid).verdict == CONSISTENT
    d = verdict(cons[1], cons[0].cid)                        # swapped vial, known contents
    assert d.verdict == SUBSTITUTED and d.matched == cons[1].cid
    assert verdict(cons[0].substituted(LIQUIDS["prop_glycol"]), cons[0].cid).verdict in (DRIFT, SUBSTITUTED)
    # few records -> no quorum -> inconclusive, never a confident guess
    d = arbitrate(cons[0].cid, [], refs)
    assert d.verdict == INCONCLUSIVE


# ------------------------------------------------------------------ firmware maths
@pytest.mark.skipif(shutil.which("gcc") is None, reason="needs host gcc")
def test_adf4351_register_maths(tmp_path):
    fw = ROOT / "firmware/pico2"
    harness = tmp_path / "t.c"
    harness.write_text(r'''
#include <stdio.h>
#include "adf4351.h"
int main(void){ adf4351_plan_t p;
  for (unsigned long long f = 2300000000ull; f <= 2500000000ull; f += 10000000ull) {
    if (!adf4351_compute(f, &p)) return 1;
    printf("%llu %llu %08x %08x %08x %08x %08x %08x\n", f, p.actual_hz,
      p.reg[0], p.reg[1], p.reg[2], p.reg[3], p.reg[4], p.reg[5]); }
  return 0; }''')
    exe = tmp_path / "t"
    subprocess.run(["gcc", "-DPGDD_HOST_TEST", f"-I{fw/'include'}", f"-I{fw/'src'}", str(harness),
                    str(fw / "src/adf4351.c"), "-o", str(exe)], check=True)
    out = subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.split("\n")
    for line in filter(None, out):
        f, act, r0, r1, r2, r3, r4, r5 = line.split()
        assert int(f) == int(act)                    # 10 MHz steps land exactly on the 100 kHz grid
        assert int(r5, 16) == 0x00580005
        r0 = int(r0, 16); r1 = int(r1, 16)
        int_n, frac, mod = r0 >> 15, (r0 >> 3) & 0xFFF, (r1 >> 3) & 0xFFF
        assert mod == 250 and abs(25e6 * (int_n + frac / mod) - int(f)) < 1
