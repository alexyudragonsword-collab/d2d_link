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
                     clocking=ClockingConfig(pll_profile=PROFILE, local_pll_profile=LOCAL, local_pll_fn_hz=2e5,
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


def test_quarter_rate_clock_with_quadrature_skew():
    """0.15.0: ``forwarded_qdr`` samples on four phases; a quadrature skew
    splits them -+q/2 on top of the duty-cycle split, and the edges' view of
    the clock (cos^2(pi f / fs) and its image since 0.15.1) shapes
    the common-mode leak. Both engines see the same four offsets."""
    cfg = LinkConfig(channel=ChannelConfig(length_mm=2.0),
                     clocking=ClockingConfig(scheme="forwarded_qdr", pll_profile=PROFILE, data_path_rj_s=1e-12,
                                             clock_path_rj_s=1e-12, dcd_ui=0.04, qdr_quadrature_ui=0.06),
                     rx=RxConfig(noise_rms_v=0.045), sim=SIM)
    r, s, t = _ratio(cfg)
    assert 0.5 < r < 2.0, (r, s.ber, t.ber)


def test_quarter_rate_clock_pieces():
    import numpy as np
    import pytest

    from d2d_link.clock.forwarded import ForwardedClock

    ddr = ForwardedClock(LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, dcd_ui=0.04)))
    assert ddr.sampling_offsets_ui() == (-0.02, 0.02) and ddr.h_edges(np.array([1e9])) is None
    q = ForwardedClock(LinkConfig(clocking=ClockingConfig(scheme="forwarded_qdr", pll_profile=PROFILE, dcd_ui=0.04,
                                                          qdr_quadrature_ui=0.06)))
    assert q.sampling_offsets_ui() == pytest.approx((-0.05, 0.01, -0.01, 0.05))
    fs = q.fs
    he = q.h_edges(np.array([0.0, fs / 4, fs / 2]))
    assert he[0] == 1.0 and he[1] == pytest.approx(0.5) and he[2] == pytest.approx(0.0, abs=1e-30)      # cos^2 (0.15.1)
    assert ddr.budget().edge_alias_s == 0.0
    plain = ForwardedClock(LinkConfig(clocking=ClockingConfig(scheme="forwarded_qdr", pll_profile=PROFILE)))
    assert plain.sampling_offsets_ui() == (0.0,)
    with pytest.raises(ValueError, match="forwarded_qdr"):
        ClockingConfig(qdr_quadrature_ui=0.01)



def test_quarter_rate_edge_aliasing_closed_form_matches_the_synthesis():
    """0.15.1: the edge sampling folds the clock path's noise at fs/2 - f onto
    f (``JitterBudget.edge_alias_s``); the synthesis does the decimation and
    linear interpolation itself. The two must give the same residual RMS
    (0.15.0 had only the in-band sinc^2 and read x1 41.7 fs low)."""
    import numpy as np
    import pytest

    from d2d_link.clock.forwarded import ForwardedClock

    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0),
                     clocking=ClockingConfig(scheme="forwarded_qdr", pll_profile=PROFILE, data_path_rj_s=200e-15,
                                             clock_path_rj_s=200e-15, tree_delay_ps=30.0, tree_bw_hz=20e9),
                     sim=SimConfig(jitter_block=1 << 16))
    fc = ForwardedClock(cfg)
    b = fc.budget()
    assert b.edge_alias_s > 0.3 * b.common_leak_s
    j = fc.synthesize(1 << 19, np.random.default_rng(7), 1)[0]
    assert float(np.std(j)) == pytest.approx(b.gaussian_s, rel=0.02)


def test_quarter_rate_offsets_and_spur_images():
    """0.15.6: a QDR clock samples on four phases whenever there is an offset
    at all (with q = 0 the order is still the clock's, not DDR's
    alternation); a Tx spur gets its edge-sampling image at fs/2 - f."""
    import pytest

    from d2d_link.clock.forwarded import ForwardedClock

    q0 = ForwardedClock(LinkConfig(clocking=ClockingConfig(scheme="forwarded_qdr", pll_profile=PROFILE, dcd_ui=0.04)))
    assert q0.sampling_offsets_ui() == pytest.approx((-0.02, -0.02, 0.02, 0.02))
    wu = "data/clock_profiles/bench_wu19_spll_frac_52m_6p253g.yaml"
    ddr = ForwardedClock(LinkConfig(clocking=ClockingConfig(pll_profile=wu, tree_delay_ps=30.0)))
    qdr = ForwardedClock(LinkConfig(clocking=ClockingConfig(scheme="forwarded_qdr", pll_profile=wu, tree_delay_ps=30.0)))
    images = [f for f, _ in qdr.spur_terms() if f > 0.25 * qdr.fs]
    assert len(qdr.spur_terms()) == 2 * len(ddr.spur_terms()) and len(images) == len(ddr.spur_terms())


def test_quarter_rate_phase_generator_jitter():
    """0.15.8: the 4-phase generator's own white jitter enters after the
    edges' interpolation, through the tracker like the tree's; closed form
    and synthesis agree, and it needs the QDR scheme."""
    import numpy as np
    import pytest

    from d2d_link.clock.forwarded import ForwardedClock

    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0),
                     clocking=ClockingConfig(scheme="forwarded_qdr", pll_profile=PROFILE, tree_delay_ps=30.0, tree_bw_hz=20e9,
                                             qdr_phase_rj_s=150e-15, track_bw_hz=5e6),
                     sim=SimConfig(jitter_block=1 << 16))
    fc = ForwardedClock(cfg)
    b = fc.budget()
    assert b.phase_gen_s == pytest.approx(150e-15, rel=0.01)                 # white, barely touched by a 5 MHz tracker
    assert float(np.std(fc.synthesize(1 << 19, np.random.default_rng(2), 1)[0])) == pytest.approx(b.gaussian_s, rel=0.02)
    with pytest.raises(ValueError, match="forwarded_qdr"):
        ClockingConfig(qdr_phase_rj_s=1e-13)
