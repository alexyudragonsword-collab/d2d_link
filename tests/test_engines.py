"""Invariant #3: the statistical engine leads; the time engine agrees within 2x
under LTI + Gaussian noise wherever it can count errors."""

import dataclasses


from conftest import PROFILE, REPO
from d2d_link.config import ChannelConfig, ClockingConfig, LinkConfig, RxConfig, SimConfig, load_config
from d2d_link.engine import run_link, run_statistical, run_time

BASE = LinkConfig(channel=ChannelConfig(length_mm=25.0),
                  clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, clock_path_rj_s=200e-15,
                                          track_bw_hz=2e6),
                  sim=SimConfig(n_symbols=400_000, stat_phase_points=32))


def _ratio(cfg):
    s = run_statistical(cfg)
    t = run_time(cfg, phase_ui=s.phase_ui)
    assert t.n_errors >= 25, f"too few errors to compare: {t.n_errors}"
    return t.ber / s.ber, s, t


def test_noise_dominated_within_2x():
    r, s, t = _ratio(dataclasses.replace(BASE, rx=RxConfig(noise_rms_v=0.05)))
    assert 0.5 < r < 2.0, (r, s.ber, t.ber)


def test_jitter_dominated_within_2x():
    cfg = dataclasses.replace(BASE, clocking=dataclasses.replace(BASE.clocking, data_path_rj_s=3e-12,
                                                                 clock_path_rj_s=3e-12, track_bw_hz=None),
                              rx=RxConfig(noise_rms_v=3e-3), sim=dataclasses.replace(BASE.sim, n_symbols=1_000_000))
    r, s, t = _ratio(cfg)
    assert 0.5 < r < 2.0, (r, s.ber, t.ber)


def test_mixed_noise_and_jitter_within_2x():
    cfg = dataclasses.replace(BASE, clocking=dataclasses.replace(BASE.clocking, data_path_rj_s=2e-12,
                                                                 clock_path_rj_s=2e-12, track_bw_hz=None),
                              rx=RxConfig(noise_rms_v=0.045), sim=dataclasses.replace(BASE.sim, n_symbols=600_000))
    r, s, t = _ratio(cfg)
    assert 0.5 < r < 2.0, (r, s.ber, t.ber)


def test_statistical_is_the_default_engine():
    cfg = load_config(REPO / "configs" / "standard_32g_x1.yaml")
    assert cfg.sim.engine == "statistical"
    res = run_link(dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, stat_phase_points=16)))
    assert res.time == [] and len(res.stat) == 1
    assert res.stat[0].ber < 1e-27                       # the target no time run could check


def test_both_engines_through_run_link():
    cfg = dataclasses.replace(BASE, rx=RxConfig(noise_rms_v=0.05),
                              sim=dataclasses.replace(BASE.sim, engine="both", n_symbols=200_000))
    res = run_link(cfg)
    (ratio,) = res.consistency_ratios()
    assert 0.5 < ratio < 2.0
    assert "time lane 0" in res.summary()
