"""Invariant #3 deep: the weekly 1e-8-class point (``pytest -m slow``).

A 2.5e9-symbol run at exactly 1e-8 takes ~5 h on one core (the waveform
engine does ~6 s per 1e6 symbols); the weekly job runs 1e9 symbols with the
noise tuned to 3e-8, ~30 errors, in under three hours. The full 1e-8 point
is the same test with ``D2D_DEEP_SYMBOLS=2500000000 D2D_DEEP_BER=1e-8``.
"""

import dataclasses
import os

import pytest

from conftest import PROFILE
from d2d_link.config import ChannelConfig, ClockingConfig, LinkConfig, RxConfig, SimConfig
from d2d_link.engine import run_statistical, run_time
from d2d_link.engine.statistical import StatisticalEngine

N_SYMBOLS = int(float(os.environ.get("D2D_DEEP_SYMBOLS", "1e9")))
TARGET = float(os.environ.get("D2D_DEEP_BER", "3e-8"))


@pytest.mark.slow
def test_deep_point_within_2x():
    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0),
                     clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, clock_path_rj_s=200e-15,
                                             track_bw_hz=2e6),
                     sim=SimConfig(n_symbols=N_SYMBOLS, stat_phase_points=32))
    eng = StatisticalEngine(cfg)
    phase = eng.run().phase_ui
    lo, hi = 1e-3, 0.3
    for _ in range(40):
        mid = (lo * hi) ** 0.5
        eng.sigma_n = mid
        if eng.error_probability(phase) > TARGET:
            hi = mid
        else:
            lo = mid
    tuned = dataclasses.replace(cfg, rx=RxConfig(noise_rms_v=(lo * hi) ** 0.5))
    s = run_statistical(tuned)
    t = run_time(tuned, phase_ui=s.phase_ui)          # jitter streamed block by block above 2^24 symbols
    print(f"deep point: statistical {s.ber:.3e}, time {t.ber:.3e} ({t.n_errors} errors in {t.error_bursts} bursts "
          f"/ {t.n_symbols:.1e}), ratio {t.ber / s.ber:.2f}")
    assert t.n_errors >= 15, t.n_errors
    assert 0.5 < t.ber / s.ber < 2.0, (t.ber, s.ber, t.n_errors)
