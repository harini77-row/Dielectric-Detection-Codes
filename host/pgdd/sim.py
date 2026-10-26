"""SimPico — a software stand-in for the trusted controller, speaking the exact
64-byte frame protocol so the host stack runs unchanged without hardware.

It mirrors firmware semantics: ROM frequency plans, view A / park / view B,
the dual-grid comparator (gate_model), poison on lock loss, a finite ring with
back-pressure, contiguous commit_idx, seq gaps for rejects, cumulative
ack / go-back-N. Physical truth (which container is actually in the cradle,
injected faults) is set on the bench, which the host cannot see.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np

from . import gate_model
from .forward import Bench, Container, signature, to_codes
from .record import (F_ENROL, F_LOCK_A, F_LOCK_B, F_TEMP_OK, F_VERIFY, CMD_ABORT, CMD_START,
                     MODE_ENROL, MODE_VERIFY, REC_COMMITTED, make_record, pack_status, parse_cmd)

PLANS = {0: (2300000, 2500000, 10000), 1: (2300000, 2500000, 5000),
         2: (2400000, 2400000, 1000), 3: (2350000, 2450000, 25000)}
RING_SLOTS = 64


def plan_freqs_khz(plan_id: int) -> list[int]:
    a, b, s = PLANS[plan_id]
    return list(range(a, b + 1, s))


@dataclass
class Faults:
    """Physical-world faults, applied per record by the simulated bench."""
    glitch_rate: float = 0.0        # one view hit by a transient (gate should reject)
    unlock_rate: float = 0.0        # PLL loses lock (poisoned -> rejected)
    slip_angles: tuple = ()         # angles where the vial is mis-seated (consistent, passes gate)
    slip_k: float = 0.04
    interf_band_khz: tuple | None = None   # steady interferer: consistent offset in band
    interf_db: float = 1.5
    interf_rate: float = 1.0
    temp_offset_c: float = 0.0
    link_error_rate: float = 0.0    # corrupt Pico->host frames on the wire


@dataclass
class BenchState:
    mounted: Container | None = None
    faults: Faults = field(default_factory=Faults)
    temp_c: float = 25.0
    placement_sd: float = 0.004
    noise_mv: float = 0.25


class SimPico:
    def __init__(self, seed: int = 0, bench: Bench = Bench(), gate_enabled: bool = True):
        self.gate_enabled = gate_enabled     # False = ablation only: admit everything
        self.rng = np.random.default_rng(seed)
        self.bench = bench
        self.state = BenchState()
        self.boot_id = int(self.rng.integers(1, 2**32))
        self.seq = 0
        self.ring: dict[int, bytes] = {}
        self.head = 0                # committed count
        self.tail = 0                # host-acked count
        self.sendptr = 0
        self.armed: bytes = b""
        self.armed_is_record = False
        self.st_state, self.st_angle, self.st_session = 0, 0, 0
        self.gen = None
        self.stats = {"committed": 0, "rejected": 0}
        self._arm()

    # ------------------------------------------------------------ physics
    def _session_gen(self, cmd: dict):
        st = self.state
        c = st.mounted
        f = st.faults
        mode = cmd["mode"]
        if c is None or cmd["plan_id"] not in PLANS or not (1 <= cmd["n_angles"] <= 12) \
                or mode not in (MODE_ENROL, MODE_VERIFY):
            return
        freqs = plan_freqs_khz(cmd["plan_id"])
        fhz = np.array(freqs, float) * 1e3
        temp = st.temp_c + f.temp_offset_c
        for a in range(cmd["n_angles"]):
            self.st_state, self.st_angle = 1, a
            pk = self.rng.normal(0, st.placement_sd)
            pph = self.rng.normal(0, np.radians(0.3))
            if a in f.slip_angles:
                pk += f.slip_k
            amp, ph = signature(c, fhz, self.bench, placement_k=pk, placement_ph=pph, temp_c=temp)
            # an unlocked PLL drifts off-frequency: view B sees a shifted point
            amp_u, ph_u = signature(c, fhz + self.rng.uniform(5e6, 30e6), self.bench,
                                    placement_k=pk, placement_ph=pph, temp_c=temp)
            if f.interf_band_khz and self.rng.random() < f.interf_rate:
                lo, hi = f.interf_band_khz
                band = (np.array(freqs) >= lo) & (np.array(freqs) <= hi)
                amp = amp + band * f.interf_db
                ph = ph + band * f.interf_db * 4
            t16 = int(round(temp * 16 + self.rng.normal(0, 1)))
            for i, fk in enumerate(freqs):
                lock = self.rng.random() >= f.unlock_rate
                ma, pa = to_codes(amp[i], ph[i], self.rng, noise_mv=st.noise_mv)
                if lock:
                    mb, pb = to_codes(amp[i], ph[i], self.rng, noise_mv=st.noise_mv)
                else:
                    mb, pb = to_codes(amp_u[i], ph_u[i], self.rng, noise_mv=st.noise_mv)
                ma, pa, mb, pb = int(ma), int(pa), int(mb), int(pb)
                if self.rng.random() < f.glitch_rate:
                    mb += int(self.rng.choice([-1, 1]) * self.rng.integers(200, 2000))
                flags = (F_ENROL if mode == MODE_ENROL else F_VERIFY) | F_TEMP_OK | \
                        (F_LOCK_A | F_LOCK_B if lock else F_LOCK_A)
                rec = make_record(seq=self.seq, t_us=int(1e6 * (self.seq + 1)), container_id=cmd["container_id"],
                                  session_id=cmd["session_id"], angle_idx=a, port=0, freq_khz=fk,
                                  vmag_a=ma, vphs_a=pa, vmag_b=mb, vphs_b=pb, temp_c16=t16, n_avg=8,
                                  boot_id=self.boot_id, plan_id=cmd["plan_id"], n_angles=cmd["n_angles"],
                                  commit_idx=self.head, flags=flags)
                self.seq += 1
                yield rec, not lock

    def _pump(self):
        """Run the session until the ring is full (firmware back-pressure)."""
        while self.gen is not None and self.head - self.tail < RING_SLOTS:
            try:
                rec, poison = next(self.gen)
            except StopIteration:
                self.gen = None
                self.st_state, self.st_angle = 0, 0
                break
            if not self.gate_enabled or gate_model.admit(rec.vmag_a, rec.vmag_b, rec.vphs_a, rec.vphs_b, poison=poison):
                b = bytearray(rec.pack())
                b[0:4] = REC_COMMITTED.to_bytes(4, "little")   # the token DMA's write
                self.ring[self.head] = bytes(b)
                self.head += 1
                self.stats["committed"] += 1
            else:
                self.stats["rejected"] += 1

    # ------------------------------------------------------------ link
    def _arm(self):
        self._pump()
        if self.head > self.sendptr:
            self.armed, self.armed_is_record = self.ring[self.sendptr], True
        else:
            self.armed = pack_status(self.boot_id, self.head, self.st_state, self.st_angle, self.st_session)
            self.armed_is_record = False

    @property
    def drdy(self) -> bool:
        return self.armed_is_record

    def xfer(self, cmd_bytes: bytes) -> bytes:
        out = self.armed
        if self.armed_is_record:
            self.sendptr += 1
        c = parse_cmd(cmd_bytes)
        if c:
            if self.tail <= c["ack"] <= self.sendptr:
                for k in range(self.tail, c["ack"]):
                    self.ring.pop(k, None)
                self.tail = c["ack"]
            if c["nack"]:
                self.sendptr = max(self.tail, c["ack"])
            if c["cmd"] == CMD_START and self.gen is None:
                self.st_session, self.st_state = c["session_id"], 1
                self.gen = self._session_gen(c)
            elif c["cmd"] == CMD_ABORT:
                self.gen, self.st_state = None, 0
        self._arm()
        if self.state.faults.link_error_rate and self.rng.random() < self.state.faults.link_error_rate:
            b = bytearray(out)
            b[int(self.rng.integers(4, 60))] ^= 0x40
            out = bytes(b)
        return out
