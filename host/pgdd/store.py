"""records.csv (provenance + raw codes, one row per committed record) and the
regenerable features.csv (amplitude_db, phase_deg, residual). Deliberately no
derived permittivity proxy: it would act as a leakage shortcut in ablations."""
from __future__ import annotations

import csv
from pathlib import Path

from .calib import DEFAULT_CAL, features
from .record import Record

REC_COLS = ["boot_id", "commit_idx", "seq", "t_us", "session_id", "container_id", "mode",
            "angle_idx", "port", "freq_khz", "vmag_a", "vphs_a", "vmag_b", "vphs_b",
            "temp_c16", "flags", "n_avg", "plan_id", "n_angles", "crc32", "host_rx_time"]
FEAT_COLS = ["boot_id", "commit_idx", "session_id", "container_id", "angle_idx", "freq_khz",
             "amplitude_db", "phase_deg", "residual"]


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.rec_path = self.root / "records.csv"
        if not self.rec_path.exists():
            with open(self.rec_path, "w", newline="") as f:
                csv.writer(f).writerow(REC_COLS)

    def add(self, r: Record, host_rx_time: float):
        row = [r.boot_id, r.commit_idx, r.seq, r.t_us, r.session_id, r.container_id,
               "enrol" if r.is_enrol else "verify", r.angle_idx, r.port, r.freq_khz,
               r.vmag_a, r.vphs_a, r.vmag_b, r.vphs_b, r.temp_c16, r.flags, r.n_avg,
               r.plan_id, r.n_angles, f"{r.crc32:08x}", f"{host_rx_time:.6f}"]
        with open(self.rec_path, "a", newline="") as f:
            csv.writer(f).writerow(row)

    def rows(self) -> list[dict]:
        with open(self.rec_path, newline="") as f:
            return list(csv.DictReader(f))

    def regenerate_features(self, refs: dict | None = None, cal=DEFAULT_CAL,
                            floor_db: float = 0.05, floor_deg: float = 0.4) -> Path:
        """residual = z-residual against the container's latest certified
        reference (blank if none, or the frequency was excluded at enrolment)."""
        from .reference import Meas
        out = self.root / "features.csv"
        refs = refs or {}
        with open(out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(FEAT_COLS)
            for row in self.rows():
                class R:  # minimal duck-type for calib.features
                    vmag_a = int(row["vmag_a"]); vmag_b = int(row["vmag_b"])
                    vphs_a = int(row["vphs_a"]); vphs_b = int(row["vphs_b"])
                a, p = features(R, cal)
                ref = refs.get(int(row["container_id"]))
                res = ""
                if ref is not None:
                    z = ref.residual(Meas(int(row["angle_idx"]), int(row["freq_khz"]), a, p), floor_db, floor_deg)
                    res = "" if z is None else z
                w.writerow([row["boot_id"], row["commit_idx"], row["session_id"], row["container_id"],
                            row["angle_idx"], row["freq_khz"], f"{a:.4f}", f"{p:.3f}",
                            f"{res:.4f}" if res != "" else ""])
        return out
