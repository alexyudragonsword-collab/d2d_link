"""Phase 3 of the plan: spurs, the tracker's feedback latency, the local PLL's
bandwidth convention, the wander band, the synthesis seam and the Tx PLL's
duty-cycle error."""

import dataclasses
import math
import warnings

import numpy as np
import pytest

from conftest import PROFILE
from d2d_link.clock.forwarded import ForwardedClock
from d2d_link.clock.profile import ClockProfile
from d2d_link.config import ClockingConfig, LinkConfig, SimConfig
from d2d_link.engine.statistical import StatisticalEngine, jitter_quadrature, run_statistical

LOCAL = "data/clock_profiles/bench_wu19_spll_frac_52m_6p253g.yaml"


def _spur_profile(tmp_path, f_hz=10e6, dbc=-40.0, floor_dbc=-190.0):
    """A clean 10 GHz clock (phase noise at the floor) with one spur."""
    f = np.logspace(2, 9.6, 40)
    return ClockProfile(10e9, f, np.full(f.size, floor_dbc), spurs=((f_hz, dbc),), source="test").save(tmp_path / "spur.yaml")


def _rms(fc, n=1 << 18, seed=0):
    return float(np.std(fc.synthesize(n, np.random.default_rng(seed))[0]))


# --------------------------------------------------------------------- spurs
def test_spur_leaks_like_the_common_noise_and_synthesis_agrees(tmp_path):
    """A -40 dBc spur at 10 MHz on the Tx PLL: common to data and clock, so it
    cancels at rho = 1 with an ideal tree, and leaks through |1 - G| when the
    tree delays the clock. Closed form (sinusoid RMS A/sqrt2 through the leak)
    and synthesis agree within 5 %."""
    prof = _spur_profile(tmp_path)
    clean = ForwardedClock(LinkConfig(clocking=ClockingConfig(pll_profile=str(prof))))
    assert clean.spur_terms() == [] and clean.budget().spur_s == 0.0 and clean.residual_sigma_s() == 0.0
    fc = ForwardedClock(LinkConfig(clocking=ClockingConfig(pll_profile=str(prof), tree_delay_ps=800.0)))
    (f0, a), = fc.spur_terms()
    amp = 2.0 * 10 ** (-40 / 20) / (2 * math.pi * 10e9)
    assert f0 == 10e6 and a == pytest.approx(amp * abs(1 - np.exp(-2j * math.pi * 10e6 * 800e-12)), rel=1e-9)
    b = fc.budget()
    assert b.spur_s == pytest.approx(a / math.sqrt(2.0), rel=1e-9) and b.spur_s > 0.95 * b.total_s
    assert b.total_s == pytest.approx(math.hypot(b.gaussian_s, b.spur_s))
    assert _rms(fc, n=1 << 20) == pytest.approx(b.total_s, rel=0.05)
    # the engine sees it as an arcsine term, not as Gaussian sigma
    eng = StatisticalEngine(LinkConfig(clocking=ClockingConfig(pll_profile=str(prof), tree_delay_ps=800.0),
                                       sim=SimConfig(stat_phase_points=16)))
    assert eng.spurs_ui == pytest.approx((a / eng.cfg.ui,)) and eng.sigma_j_ui == pytest.approx(b.gaussian_s / eng.cfg.ui)
    x, w = eng.nodes, eng.weights
    assert float(np.sum(w * x ** 2)) == pytest.approx((a / eng.cfg.ui) ** 2 / 2 + eng.sigma_j_ui ** 2, rel=0.02)


def test_local_pll_spur_leaks_through_one_minus_h(tmp_path):
    prof = _spur_profile(tmp_path, f_hz=50e6, dbc=-50.0)
    fc = ForwardedClock(LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, local_pll_profile=str(prof),
                                                           local_pll_fn_hz=1e6)))
    (f0, a), = fc.spur_terms()
    amp = 2.0 * 10 ** (-50 / 20) / (2 * math.pi * 10e9)
    h = fc.h_pll(np.array([50e6]))[0]
    assert a == pytest.approx(amp * abs(1 - h), rel=1e-9) and abs(1 - h) > 0.9   # far above the loop: all of it


def test_arcsine_kernel_is_normalised_with_the_right_variance():
    x, w = jitter_quadrature(0.0, 64, 12.0, 0.0, (0.05,))
    assert w.sum() == pytest.approx(1.0) and float(np.sum(w * x ** 2)) == pytest.approx(0.05 ** 2 / 2, rel=0.01)
    assert np.all(np.abs(x[w > 0]) <= 0.05 + (x[1] - x[0]))                # support [-A, A], to the bin that straddles the edge
    xs, ws = jitter_quadrature(0.01, 64, 12.0, 0.0, (0.05, 0.02))
    assert ws.sum() == pytest.approx(1.0)
    assert float(np.sum(ws * xs ** 2)) == pytest.approx(0.01 ** 2 + 0.05 ** 2 / 2 + 0.02 ** 2 / 2, rel=0.01)


def test_spur_dominated_link_both_engines_agree(tmp_path):
    """Invariant #3 on a deterministic sinusoidal jitter: a large spur through
    a delaying tree, sampler noise tuned to 1e-4 at the eye centre."""
    from d2d_link.engine import run_time

    prof = _spur_profile(tmp_path, f_hz=20e6, dbc=-16.0)
    cfg = LinkConfig(channel=dataclasses.replace(LinkConfig().channel, length_mm=25.0),
                     clocking=ClockingConfig(pll_profile=str(prof), tree_delay_ps=2500.0, data_path_rj_s=100e-15),
                     sim=SimConfig(n_symbols=600_000, stat_phase_points=32))
    eng = StatisticalEngine(cfg)
    assert eng.spurs_ui and eng.spurs_ui[0] > 0.03                   # the spur, not the noise, sets the margin
    phase = eng.run().phase_ui
    lo, hi = 1e-4, 0.5
    for _ in range(36):
        mid = (lo * hi) ** 0.5
        eng.sigma_n = mid
        if eng.error_probability(phase) > 1e-4:
            hi = mid
        else:
            lo = mid
    tuned = dataclasses.replace(cfg, rx=dataclasses.replace(cfg.rx, noise_rms_v=(lo * hi) ** 0.5))
    s = run_statistical(tuned)
    t = run_time(tuned, phase_ui=s.phase_ui)
    assert t.n_errors >= 25 and 0.5 < t.ber / s.ber < 2.0, (t.ber, s.ber, t.n_errors)


# ------------------------------------------------------------------- tracker
def test_tracker_latency_is_in_the_feedback_path():
    """theta[k] = theta[k-1] + alpha (delta[k-d] - theta[k-1-d]): at d = 0 the
    old first-order loop; with latency a fast loop peaks and then diverges,
    which the constructor refuses instead of synthesising."""
    assert ForwardedClock.tracker_stability_margin(0.3, 0) == pytest.approx(0.3)
    assert ForwardedClock.tracker_stability_margin(1.0, 1) == pytest.approx(0.0, abs=1e-12)   # marginal
    assert ForwardedClock.tracker_stability_margin(0.3, 8) < 0.0 < ForwardedClock.tracker_stability_margin(0.1, 8)
    with pytest.raises(ValueError, match="unstable"):
        ForwardedClock(LinkConfig(clocking=ClockingConfig(data_path_rj_s=200e-15, track_bw_hz=math.inf, track_delay_ui=1)))
    with pytest.raises(ValueError, match="unstable"):
        ForwardedClock(LinkConfig(clocking=ClockingConfig(data_path_rj_s=200e-15, track_bw_hz=2e9, track_delay_ui=8)))
    # a stable but latent loop peaks: white path noise comes out above its input
    fc = ForwardedClock(LinkConfig(clocking=ClockingConfig(data_path_rj_s=200e-15, track_bw_hz=5e8, track_delay_ui=8)))
    assert 0.0 < fc.tracker_stability_margin(fc.alpha, 8) < 0.1
    assert fc.residual_sigma_s() > 1.03 * 200e-15
    assert _rms(fc, n=1 << 19) == pytest.approx(fc.residual_sigma_s(), rel=0.05)
    # zero latency is unchanged: the same transfer function as before
    z0 = ForwardedClock(LinkConfig(clocking=ClockingConfig(data_path_rj_s=200e-15, track_bw_hz=2e6)))
    f = z0.fft_grid()
    z_inv = np.exp(-2j * math.pi * f * z0.ui)
    assert np.allclose(z0.e_track(f), 1 - z0.alpha / (1 - (1 - z0.alpha) * z_inv))


# ----------------------------------------------------------------- local PLL
def test_local_pll_natural_frequency_and_minus_3db():
    fc = ForwardedClock(LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, local_pll_profile=LOCAL,
                                                           local_pll_fn_hz=1e6)))
    f3 = fc.local_pll_bw_3db_hz()
    assert f3 == pytest.approx(1e6 * math.sqrt(3 + math.sqrt(10)), rel=1e-9)    # 2.48 f_n at zeta = 1
    assert abs(fc.h_pll(np.array([f3]))[0]) == pytest.approx(1 / math.sqrt(2.0), rel=1e-6)
    assert ForwardedClock(LinkConfig()).local_pll_bw_3db_hz() is None


def test_old_loop_bandwidth_key_still_loads_with_a_warning(tmp_path):
    from d2d_link.config import load_config

    p = tmp_path / "old.yaml"
    p.write_text("clocking:\n  local_pll_profile: " + LOCAL + "\n  local_pll_bw_hz: 1.0e6\n", encoding="utf-8")
    with pytest.warns(DeprecationWarning, match="local_pll_fn_hz"):
        cfg = load_config(p)
    assert cfg.clocking.local_pll_fn_hz == 1e6
    p.write_text("clocking:\n  local_pll_profile: " + LOCAL + "\n  local_pll_bw_hz: 1.0e6\n  local_pll_fn_hz: 2.0e6\n",
                 encoding="utf-8")
    with pytest.raises(KeyError, match="both"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        load_config(p)


# -------------------------------------------------------------------- wander
def test_wander_rms_is_defined_on_a_physical_band():
    cfg = LinkConfig(clocking=ClockingConfig(data_path_wander_s=500e-15))
    fc = ForwardedClock(cfg)
    assert fc.wander_floor_hz == pytest.approx(fc.fs / cfg.sim.jitter_block)
    fc_floor = ForwardedClock(dataclasses.replace(cfg, clocking=dataclasses.replace(cfg.clocking, wander_floor_hz=1e5)))
    f = np.linspace(fc_floor.wander_floor_hz, 0.5 * fc.fs, 2_000_001)
    trapezoid = getattr(np, "trapezoid", None) or np.trapz
    assert float(trapezoid(fc_floor.wander_psd(500e-15, f), f)) == pytest.approx((500e-15) ** 2, rel=1e-3)
    # a lower floor puts more of the RMS below the band the grid sees -> less on the grid
    lower = ForwardedClock(dataclasses.replace(cfg, clocking=dataclasses.replace(cfg.clocking, wander_floor_hz=1e3)))
    assert lower.residual_sigma_s() < fc.residual_sigma_s() < 1.1 * 500e-15
    # the block size no longer changes the PSD level once the floor is pinned
    big = ForwardedClock(dataclasses.replace(fc_floor.cfg, sim=dataclasses.replace(cfg.sim, jitter_block=1 << 20)))
    assert big.wander_psd(500e-15, np.array([1e6])) == pytest.approx(fc_floor.wander_psd(500e-15, np.array([1e6])))


# ------------------------------------------------------------- synthesis seam
def test_block_seam_is_measured():
    cfg = LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, tree_delay_ps=50.0),
                     sim=dataclasses.replace(LinkConfig().sim, jitter_block=4096))
    fc = ForwardedClock(cfg)
    assert math.isnan(fc.block_step_ratio)
    fc.synthesize(4096, np.random.default_rng(0))
    assert math.isnan(fc.block_step_ratio)                            # one block: no seam to measure
    fc.synthesize(16 * 4096, np.random.default_rng(0))
    assert np.isfinite(fc.block_step_ratio) and fc.block_step_ratio > 0.0
    assert ForwardedClock._block_step_ratio(np.arange(20.0), 5) == pytest.approx(1.0)   # a ramp has no seam


# -------------------------------------------------------------------- Tx DCD
def test_tx_duty_cycle_error_is_common_mode_until_a_local_pll_regenerates_the_clock():
    base = ClockingConfig(pll_profile=PROFILE, tx_dcd_ui=0.1)
    assert base.sampling_dcd_ui == 0.0
    with_pll = dataclasses.replace(base, local_pll_profile=LOCAL, local_pll_fn_hz=1e6)
    assert with_pll.sampling_dcd_ui == pytest.approx(0.1)
    assert dataclasses.replace(with_pll, dcd_ui=0.02).sampling_dcd_ui == pytest.approx(0.12)
    sim = SimConfig(stat_phase_points=16)
    plain = run_statistical(LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE), sim=sim))
    cm = run_statistical(LinkConfig(clocking=base, sim=sim))
    assert cm.eye_width_ui == plain.eye_width_ui and cm.eye_height_v == plain.eye_height_v
    rx = run_statistical(LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, dcd_ui=0.1), sim=sim))
    assert rx.eye_width_ui < plain.eye_width_ui - 0.05


def test_tree_delay_wrap_is_a_number():
    fc = ForwardedClock(LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, tree_delay_ps=30.0)))
    assert fc.tree_wrap_fraction == pytest.approx(30e-12 / (fc.cfg.sim.jitter_block * fc.ui))
    assert fc.tree_wrap_fraction < 1e-5 and ForwardedClock(LinkConfig()).tree_wrap_fraction == 0.0
