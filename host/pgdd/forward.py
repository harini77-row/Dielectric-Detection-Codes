"""Synthetic forward model: liquid (Cole-Cole) -> loaded-antenna reflection ->
AD8302 amplitude/phase -> ADS1115 codes.

This is a *signature generator* for exercising the pipeline, not a validated
EM model. Real antenna-liquid near-field coupling is deferred to hardware and
the Phase 0 VNA data. Liquid parameters are approximate, for synthesis only.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import numpy as np

from .calib import DEFAULT_CAL, AD8302Cal

EPS0 = 8.854e-12


@dataclass(frozen=True)
class Liquid:
    name: str
    eps_s: float
    eps_inf: float
    tau_ps: float
    alpha: float = 0.0
    sigma: float = 0.0          # S/m

    def eps(self, f_hz: np.ndarray, temp_c: float = 25.0) -> np.ndarray:
        dt = temp_c - 25.0
        eps_s = self.eps_s * (1.0 - 0.0046 * dt)
        tau = self.tau_ps * 1e-12 * (1.0 - 0.02 * dt)
        w = 2 * np.pi * f_hz
        e = self.eps_inf + (eps_s - self.eps_inf) / (1 + (1j * w * tau) ** (1 - self.alpha))
        return e - 1j * self.sigma / (w * EPS0)


LIQUIDS = {
    "water":      Liquid("water", 78.4, 5.2, 8.3),
    "saline_0.9": Liquid("saline_0.9", 77.0, 5.2, 8.3, sigma=1.6),
    "dextrose_5": Liquid("dextrose_5", 75.5, 5.0, 9.4, sigma=0.05),
    "ethanol":    Liquid("ethanol", 24.3, 4.2, 163.0, alpha=0.05),
    "glycerol_50": Liquid("glycerol_50", 64.0, 4.8, 27.0, alpha=0.1),
    "prop_glycol": Liquid("prop_glycol", 32.0, 3.5, 60.0, alpha=0.15),
}


@dataclass(frozen=True)
class Container:
    cid: int
    liquid: Liquid
    vial_k: float = 0.0         # per-vial coupling deviation (glass, fill height)
    vial_q: float = 0.0         # per-vial Q deviation

    def degraded(self, d_eps_s: float = -1.5, d_sigma: float = 0.1) -> "Container":
        """Subtle content change (degradation-like)."""
        l = replace(self.liquid, name=self.liquid.name + "*",
                    eps_s=self.liquid.eps_s + d_eps_s, sigma=self.liquid.sigma + d_sigma)
        return replace(self, liquid=l)

    def substituted(self, liquid: Liquid) -> "Container":
        """Same vial, different contents."""
        return replace(self, liquid=liquid)


@dataclass(frozen=True)
class Bench:
    f0_hz: float = 2.62e9       # unloaded antenna resonance
    k_fill: float = 0.0022      # liquid coupling into effective permittivity
    q0: float = 18.0
    kq: float = 0.004
    r_match: float = 1.25
    cable_ns: float = 0.45
    cal: AD8302Cal = DEFAULT_CAL


def reflection(c: Container, f_hz: np.ndarray, bench: Bench = Bench(),
               placement_k: float = 0.0, placement_ph: float = 0.0,
               temp_c: float = 25.0) -> np.ndarray:
    e = c.liquid.eps(f_hz, temp_c)
    k = bench.k_fill * (1 + c.vial_k + placement_k)
    eps_eff = 1 + k * (e.real - 1)
    fr = bench.f0_hz / np.sqrt(eps_eff)
    inv_q = 1 / (bench.q0 * (1 + c.vial_q)) + bench.kq * (k / bench.k_fill) * (-e.imag)
    q = 1 / inv_q
    z = bench.r_match * (1 + 1j * q * (f_hz / fr - fr / f_hz))
    g = (z - 1) / (z + 1)
    return g * np.exp(-1j * (2 * np.pi * f_hz * bench.cable_ns * 1e-9 * 2 + placement_ph))


def signature(c: Container, f_hz: np.ndarray, bench: Bench = Bench(), **kw):
    g = reflection(c, f_hz, bench, **kw)
    amp_db = 20 * np.log10(np.maximum(np.abs(g), 1e-4))
    amp_db = np.clip(amp_db, -30.0, 30.0)               # AD8302 range
    ph = np.degrees(np.abs(np.angle(g)))                 # 0..180, sign lost
    return amp_db, ph


def to_codes(amp_db, ph_deg, rng: np.random.Generator, cal: AD8302Cal = DEFAULT_CAL,
             noise_mv: float = 0.25, n_avg: int = 8):
    """Detector + RC + ADS1115 with averaging. Returns integer codes."""
    sd = noise_mv * 1e-3 / np.sqrt(n_avg) / (2.048 / 32768)
    m = np.rint(cal.code_from_db(np.asarray(amp_db)) + rng.normal(0, sd, np.shape(amp_db)))
    p = np.rint(cal.code_from_deg(np.asarray(ph_deg)) + rng.normal(0, sd, np.shape(ph_deg)))
    return np.clip(m, -32768, 32767).astype(int), np.clip(p, -32768, 32767).astype(int)


def make_containers(n: int, rng: np.random.Generator, liquids=None, vial_sd=0.02) -> list[Container]:
    names = liquids or list(LIQUIDS)
    return [Container(cid=100 + i, liquid=LIQUIDS[names[i % len(names)]],
                      vial_k=float(rng.normal(0, vial_sd)), vial_q=float(rng.normal(0, vial_sd)))
            for i in range(n)]
