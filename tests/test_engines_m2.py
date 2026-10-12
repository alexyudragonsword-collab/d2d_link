"""Invariant #3 on the milestone-2 mechanisms: local PLL, tracker quantisation and
latency, the advanced package, a CTLE, a duty-cycle error."""

import dataclasses

from conftest import PROFILE
from d2d_link.config import (ChannelConfig, ClockingConfig, CtleConfig, LinkConfig, PackageConfig, RxConfig,
                             SimConfig)
from d2d_link.engine import run_statistical, run_time
from d2d_link.engine.statistical import StatisticalEngine

LOCAL = "data/clock_profiles/bench_wu19_spll_frac_52m_6p253g.yaml"
SIM = SimConfig(n_symbols=600_000, stat_phase_points=32)


def _tuned(cfg, target=1e-4):
    """``cfg`` with its sampler noise set so the statistics predict ``target``
    at the eye centre (one engine, the ISI models do not depend on the noise)."""
    eng = StatisticalEngine(cfg)
    phase = eng.run().phase_ui
    lo, hi = 1e-4, 0.5
    for _ in range(36):
        mid = (lo * hi) ** 0.5
        eng.sigma_n = mid
        if eng.error_probability(phase) > target:
            hi = mid
        else:
            lo = mid
    return dataclasses.replace(cfg, rx=dataclasses.replace(cfg.rx, noise_rms_v=(lo * hi) ** 0.5))


def _ratio(cfg, min_errors=25):
    cfg = _tuned(cfg)
    s = run_statistical(cfg)
    t = run_time(cfg, phase_ui=s.phase_ui)
    assert t.n_errors >= min_errors, f"too few errors to compare: {t.n_errors}"
    return t.ber / s.ber, s, t


def test_local_pll_jitter_dominated():
    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0),
                     clocking=ClockingConfig(pll_profile=PROFILE, local_pll_profile=LOCAL, local_pll_bw_hz=2e5,
                                             local_pll_shift_db=30.0, pll_shift_db=30.0),
                     rx=RxConfig(noise_rms_v=0.02), sim=SIM)
    r, s, t = _ratio(cfg)
    assert s.jitter.local_pll_s > 1e-12 and s.jitter.common_leak_s > 1e-12
    assert s.sigma_jitter_s / cfg.ui > 0.05           # the clock, not only the noise, sets the margin
    assert 0.5 < r < 2.0, (r, s.ber, t.ber)


def test_quantised_delayed_tracker():
    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0),
                     clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=2e-12, clock_path_rj_s=2e-12,
                                             track_bw_hz=5e8, track_delay_ui=4, pi_step_ui=0.03),
                     rx=RxConfig(noise_rms_v=0.03), sim=SIM)
    r, s, t = _ratio(cfg)
    assert s.extras["quantisation_ui"] == 0.03
    assert 0.5 < r < 2.0, (r, s.ber, t.ber)


def test_advanced_package_with_ctle_and_dcd():
    cfg = LinkConfig(package=PackageConfig(kind="advanced"), channel=ChannelConfig(length_mm=2.0),
                     clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=1e-12, clock_path_rj_s=1e-12,
                                             dcd_ui=0.06),
                     rx=RxConfig(noise_rms_v=0.045, ctle=CtleConfig(enable=True, peak_db=3.0)), sim=SIM)
    r, s, t = _ratio(cfg)
    assert 0.5 < r < 2.0, (r, s.ber, t.ber)


def test_wander_dominated_with_tracker():
    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0),
                     clocking=ClockingConfig(pll_profile=PROFILE, data_path_wander_s=6e-12, track_bw_hz=5e6,
                                             wander_corner_hz=2e6),
                     rx=RxConfig(noise_rms_v=0.01), sim=dataclasses.replace(SIM, n_symbols=1_000_000))
    r, s, t = _ratio(cfg)
    assert 0.5 < r < 2.0, (r, s.ber, t.ber)
