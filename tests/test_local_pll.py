"""Invariant #2, milestone 2: the receiver's local PLL is locked to the forwarded
clock; path wander, tracker latency and phase-interpolator quantisation."""

import dataclasses
import math

import numpy as np
import pytest

from conftest import PROFILE
from d2d_link.clock.forwarded import ForwardedClock, residual_vs_local_pll_bw
from d2d_link.config import ClockingConfig, LinkConfig

LOCAL = "data/clock_profiles/bench_wu19_spll_frac_52m_6p253g.yaml"


def _fc(**kw):
    return ForwardedClock(LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, **kw)))


def _rms(fc, n=1 << 18, seed=0):
    return float(np.std(fc.synthesize(n, np.random.default_rng(seed))[0]))


def test_local_pll_needs_a_loop_bandwidth():
    with pytest.raises(ValueError, match="locked"):
        ClockingConfig(local_pll_profile=LOCAL)
    ck = ClockingConfig(local_pll_profile=LOCAL, local_pll_fn_hz=1e6)
    assert ck.has_local_pll and not ClockingConfig().has_local_pll


def test_infinite_loop_bandwidth_hides_the_local_pll_entirely():
    fc = _fc(local_pll_profile=LOCAL, local_pll_fn_hz=1e13)
    assert fc.local_pll_rms_s() > 50e-15                 # the local clock is far from clean
    assert fc.residual_sigma_s() == pytest.approx(0.0, abs=1e-18)
    assert _rms(fc) == pytest.approx(0.0, abs=1e-17)


def test_zero_loop_bandwidth_is_two_independent_clocks():
    fc = _fc(local_pll_profile=LOCAL, local_pll_fn_hz=1e3)
    expect = math.hypot(fc.pll_rms_s(), fc.local_pll_rms_s())
    assert fc.residual_sigma_s() == pytest.approx(expect, rel=0.01)
    b = fc.budget()
    assert b.common_leak_s == pytest.approx(fc.pll_rms_s(), rel=0.01)
    assert b.local_pll_s == pytest.approx(fc.local_pll_rms_s(), rel=0.01)


def test_loop_bandwidth_trades_tx_leak_against_local_noise():
    bws = [1e4, 1e5, 1e6, 1e7, 1e8, 1e9]
    budgets = residual_vs_local_pll_bw(LinkConfig(clocking=ClockingConfig(
        pll_profile=PROFILE, local_pll_profile=LOCAL, local_pll_fn_hz=1e6)), bws)
    leak = [b.common_leak_s for b in budgets]
    local = [b.local_pll_s for b in budgets]
    assert all(np.diff(leak) < 0)              # more bandwidth: less of the Tx PLL leaks
    assert local[0] > local[-1] > 0.0          # and the local noise above the loop shrinks too
    tot = [b.total_s for b in budgets]
    assert tot[0] > tot[-1]


def test_local_pll_closed_form_matches_synthesis():
    fc = _fc(local_pll_profile=LOCAL, local_pll_fn_hz=1e7, data_path_rj_s=150e-15,
             clock_path_rj_s=100e-15, tree_delay_ps=20.0, tree_bw_hz=15e9)
    assert _rms(fc, n=1 << 20, seed=3) == pytest.approx(fc.residual_sigma_s(), rel=0.05)


def test_local_pll_white_only():
    fc = ForwardedClock(LinkConfig(clocking=ClockingConfig(local_pll_rj_s=300e-15, local_pll_fn_hz=1e6)))
    # white local noise above a 1 MHz loop on a 16 GHz edge rate: almost all of it stays
    assert 0.95 * 300e-15 < fc.residual_sigma_s() < 300e-15
    assert _rms(fc) == pytest.approx(fc.residual_sigma_s(), rel=0.03)


def test_damping_changes_the_peaking_not_the_limits():
    a = _fc(local_pll_profile=LOCAL, local_pll_fn_hz=1e6, local_pll_damping=0.3).residual_sigma_s()
    b = _fc(local_pll_profile=LOCAL, local_pll_fn_hz=1e6, local_pll_damping=2.0).residual_sigma_s()
    assert a != b and a > 0 and b > 0


def test_wander_is_normalised_and_tracked():
    fc = ForwardedClock(LinkConfig(clocking=ClockingConfig(data_path_wander_s=500e-15)))
    # the RMS is defined on [floor, fs/2] analytically; the grid sum sees ~4 % more (half a bin at each end)
    assert fc.residual_sigma_s() == pytest.approx(500e-15, rel=0.05)
    assert _rms(fc, n=1 << 20) == pytest.approx(500e-15, rel=0.08)   # 1/f^2-like: one realisation scatters
    tracked = ForwardedClock(LinkConfig(clocking=ClockingConfig(data_path_wander_s=500e-15, track_bw_hz=20e6)))
    assert tracked.residual_sigma_s() < 0.3 * 500e-15
    assert _rms(tracked) == pytest.approx(tracked.residual_sigma_s(), rel=0.05)
    # white path noise at the same tracker bandwidth is hardly touched
    white = ForwardedClock(LinkConfig(clocking=ClockingConfig(data_path_rj_s=500e-15, track_bw_hz=20e6)))
    assert white.residual_sigma_s() > 0.95 * 500e-15


def test_tracker_latency_costs_tracking():
    """Latency in the loop (phase 3: in the feedback path too) leaves more of
    a slow wander; the fast-and-latent extreme is unstable and refused, see
    tests/test_clock_fidelity.py."""
    slow = ForwardedClock(LinkConfig(clocking=ClockingConfig(data_path_wander_s=500e-15, track_bw_hz=20e6,
                                                             track_delay_ui=8)))
    fast = ForwardedClock(LinkConfig(clocking=ClockingConfig(data_path_wander_s=500e-15, track_bw_hz=20e6)))
    assert slow.residual_sigma_s() > fast.residual_sigma_s()
    assert _rms(slow, n=1 << 19) == pytest.approx(slow.residual_sigma_s(), rel=0.08)


def test_pi_quantisation_adds_a_uniform_step():
    cfg = LinkConfig(clocking=ClockingConfig(data_path_rj_s=200e-15, track_bw_hz=1e9, pi_step_ui=0.01))
    fc = ForwardedClock(cfg)
    lin = fc.residual_sigma_s()
    q = fc.quantisation_sigma_s()
    assert q == pytest.approx(0.01 * cfg.ui / math.sqrt(12.0))
    assert _rms(fc, n=1 << 19) == pytest.approx(math.hypot(lin, q), rel=0.05)
    # no tracker: nothing to quantise
    assert ForwardedClock(dataclasses.replace(cfg, clocking=dataclasses.replace(cfg.clocking, track_bw_hz=None))
                          ).quantisation_sigma_s() == 0.0
