"""ADS1115 code -> volts -> AD8302 amplitude/phase.

Honest feature set: amplitude_db, phase_deg (and later residual). Nothing here
is, or should be described as, a permittivity measurement — the geometry
yields a dielectric *signature*, not an absolute dielectric constant.
"""
from __future__ import annotations

from dataclasses import dataclass

ADS_FS_V = 2.048
ADS_LSB_V = ADS_FS_V / 32768.0          # 62.5 uV


@dataclass(frozen=True)
class AD8302Cal:
    # Datasheet nominals; replace with a two-point calibration per board.
    vmag_center_v: float = 0.900        # 0 dB ratio
    vmag_slope_v_per_db: float = 0.030
    vphs_zero_deg_v: float = 1.800      # 0 deg
    vphs_slope_v_per_deg: float = -0.010

    def amplitude_db(self, code: float) -> float:
        v = code * ADS_LSB_V
        return (v - self.vmag_center_v) / self.vmag_slope_v_per_db

    def phase_deg(self, code: float) -> float:
        """|phase difference| in 0..180 deg. The AD8302 cannot resolve sign."""
        v = code * ADS_LSB_V
        return min(180.0, max(0.0, (v - self.vphs_zero_deg_v) / self.vphs_slope_v_per_deg))

    # inverses, used by the simulator
    def code_from_db(self, db: float) -> float:
        return (self.vmag_center_v + self.vmag_slope_v_per_db * db) / ADS_LSB_V

    def code_from_deg(self, deg: float) -> float:
        return (self.vphs_zero_deg_v + self.vphs_slope_v_per_deg * deg) / ADS_LSB_V


DEFAULT_CAL = AD8302Cal()


def features(rec, cal: AD8302Cal = DEFAULT_CAL) -> tuple[float, float]:
    """Mean of the two admitted views."""
    a = 0.5 * (cal.amplitude_db(rec.vmag_a) + cal.amplitude_db(rec.vmag_b))
    p = 0.5 * (cal.phase_deg(rec.vphs_a) + cal.phase_deg(rec.vphs_b))
    return a, p
