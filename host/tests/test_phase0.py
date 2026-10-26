import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "phase0"))
import touchstone  # noqa: E402
from variance_decomp import nested_anova  # noqa: E402


def test_nested_anova_recovers_components():
    rng = np.random.default_rng(0)
    V, P, R, N = 40, 6, 5, 50
    sv, sp, sn = 2.0, 0.7, 0.3
    Y = (rng.normal(0, sv, (V, 1, 1, N)) + rng.normal(0, sp, (V, P, 1, N)) + rng.normal(0, sn, (V, P, R, N)))
    d = nested_anova(Y)
    assert abs(np.sqrt(d["s2_vial"].mean()) - sv) < 0.3
    assert abs(np.sqrt(d["s2_place"].mean()) - sp) < 0.1
    assert abs(np.sqrt(d["s2_noise"].mean()) - sn) < 0.03


def test_touchstone_roundtrip(tmp_path):
    f = np.linspace(2.3e9, 2.5e9, 11)
    s = 0.3 * np.exp(1j * np.linspace(0, 3, 11))
    touchstone.write_s1p(tmp_path / "a.s1p", f, s)
    f2, S = touchstone.read(tmp_path / "a.s1p")
    assert np.allclose(f, f2) and np.allclose(S[:, 0, 0], s)
