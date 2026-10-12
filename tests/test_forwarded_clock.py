"""Invariant #2: the forwarded clock tracks the transmit PLL.

Acceptance: correlation 1 -> zero residual; tracker bandwidth -> inf -> zero;
no tracker -> the two paths' independent jitters add in power; closed form and
synthesis agree.
"""

import dataclasses
import math

import numpy as np
import pytest

from conftest import PROFILE
from d2d_link.clock.forwarded import ForwardedClock, residual_vs_track_bw
from d2d_link.config import ClockingConfig, LinkConfig


def _cfg(**kw):
    return LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, **kw))


def _rms(fc, n=1 << 18, seed=0):
    return float(np.std(fc.synthesize(n, np.random.default_rng(seed))[0]))


def test_pll_has_jitter_but_correlation_one_leaves_zero():
    fc = ForwardedClock(_cfg())
    assert fc.pll_rms_s() > 100e-15                 # the clock is far from clean
    assert fc.residual_sigma_s() == 0.0             # and none of it reaches the sampler
    assert _rms(fc) == 0.0


def test_correlation_one_with_white_pll_also_zero():
    fc = ForwardedClock(LinkConfig(clocking=ClockingConfig(pll_rj_s=500e-15)))
    assert fc.pll_rms_s() == pytest.approx(500e-15, rel=1e-9)
    assert fc.residual_sigma_s() == 0.0 and _rms(fc) == 0.0


def test_infinite_tracker_bandwidth_removes_everything():
    fc = ForwardedClock(_cfg(data_path_rj_s=300e-15, clock_path_rj_s=200e-15, tree_rj_s=100e-15,
                             correlation=0.5, tree_delay_ps=80.0, track_bw_hz=math.inf))
    assert fc.alpha == 1.0
    assert fc.residual_sigma_s() == 0.0
    assert _rms(fc) == pytest.approx(0.0, abs=1e-30)


def test_no_tracker_gives_power_sum_of_independent_paths():
    sd, sk = 300e-15, 200e-15
    fc = ForwardedClock(_cfg(data_path_rj_s=sd, clock_path_rj_s=sk))
    expect = math.hypot(sd, sk)
    assert fc.residual_sigma_s() == pytest.approx(expect, rel=1e-9)
    assert fc.budget().common_leak_s == 0.0
    assert _rms(fc, n=1 << 20) == pytest.approx(expect, rel=0.02)


def test_residual_falls_monotonically_with_tracker_bandwidth():
    cfg = _cfg(data_path_rj_s=300e-15, clock_path_rj_s=200e-15)
    bws = [None, 1e5, 1e6, 1e7, 1e8, 1e9, 1e10, math.inf]
    r = residual_vs_track_bw(cfg, bws)
    assert np.all(np.diff(r) <= 1e-18)
    assert r[0] == pytest.approx(math.hypot(300e-15, 200e-15), rel=1e-9) and r[-1] == 0.0


def test_correlation_zero_is_two_independent_clocks():
    fc = ForwardedClock(_cfg(correlation=0.0))
    assert fc.residual_sigma_s() == pytest.approx(math.sqrt(2.0) * fc.pll_rms_s(), rel=1e-9)


def test_tree_delay_leaks_the_common_part_as_a_differentiator():
    tau = 50e-12
    fc = ForwardedClock(_cfg(tree_delay_ps=tau * 1e12))
    f = fc.fft_grid()
    df = f[1] - f[0]
    expect = math.sqrt(float(np.sum(np.abs(1 - np.exp(-2j * np.pi * f * tau)) ** 2 * fc.pll_timing_psd(f)) * df))
    assert fc.residual_sigma_s() == pytest.approx(expect, rel=1e-9)
    assert 0.0 < fc.residual_sigma_s() < fc.pll_rms_s()
    assert _rms(fc) == pytest.approx(fc.residual_sigma_s(), rel=0.05)


def test_tree_bandwidth_leaks_the_high_frequency_common_part():
    r = [ForwardedClock(_cfg(tree_bw_hz=bw)).residual_sigma_s() for bw in (2e9, 10e9, 50e9)]
    assert r[0] > r[1] > r[2] > 0.0


def test_closed_form_matches_synthesis_with_everything_on():
    fc = ForwardedClock(_cfg(correlation=0.9, data_path_rj_s=250e-15, clock_path_rj_s=150e-15,
                             tree_rj_s=100e-15, tree_delay_ps=40.0, tree_bw_hz=12e9, track_bw_hz=5e6))
    assert _rms(fc, n=1 << 20, seed=4) == pytest.approx(fc.residual_sigma_s(), rel=0.05)


def test_tracker_alpha_mapping():
    ui = 31.25e-12
    assert ForwardedClock.tracker_alpha(None, ui) == 0.0
    assert ForwardedClock.tracker_alpha(math.inf, ui) == 1.0
    a = ForwardedClock.tracker_alpha(1e6, ui)
    assert a == pytest.approx(2 * math.pi * 1e6 * ui, rel=1e-3)


def test_lanes_share_the_clock_but_not_the_data_path():
    fc = ForwardedClock(_cfg(correlation=0.8, data_path_rj_s=0.0))
    eps = fc.synthesize(1 << 14, np.random.default_rng(1), n_lanes=3)
    assert np.array_equal(eps[0], eps[1]) and np.array_equal(eps[1], eps[2])
    fc2 = ForwardedClock(_cfg(correlation=0.8, data_path_rj_s=200e-15))
    eps2 = fc2.synthesize(1 << 14, np.random.default_rng(1), n_lanes=2)
    assert not np.array_equal(eps2[0], eps2[1])


def test_profile_shift_scales_the_leak():
    base = ForwardedClock(_cfg(tree_delay_ps=50.0)).residual_sigma_s()
    up = ForwardedClock(_cfg(tree_delay_ps=50.0, pll_shift_db=20.0)).residual_sigma_s()
    assert up == pytest.approx(10.0 * base, rel=1e-9)


def test_block_tail_keeps_the_grid():
    cfg = dataclasses.replace(_cfg(data_path_rj_s=200e-15), sim=dataclasses.replace(LinkConfig().sim, jitter_block=1024))
    eps = ForwardedClock(cfg).synthesize(2500, np.random.default_rng(2))
    assert eps.shape == (1, 2500) and np.all(np.isfinite(eps))
