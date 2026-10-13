"""Statistical engine: closed forms and the 1e-27 reach."""

import dataclasses

import numpy as np
import pytest
from scipy.special import erfcinv

from conftest import PROFILE
from d2d_link.channel.model import LinkResponse
from d2d_link.config import ChannelConfig, ClockingConfig, LinkConfig, RxConfig, SimConfig, load_config
from d2d_link.engine.statistical import (StatisticalEngine, isi_model, jitter_quadrature, log10_tail, qfunc,
                                         run_statistical, tail_probability)
from d2d_link.vendor.halo.waveform import Waveform


def _flat_response(cfg: LinkConfig, amp: float, width_ui: float = 1.0) -> LinkResponse:
    """An ideal rectangular pulse of height ``amp`` and width ``width_ui``
    (1 UI: no ISI at all)."""
    osr = cfg.sim.osr
    p = np.zeros(8 * osr)
    p[2 * osr:int(round((2.0 + width_ui) * osr))] = amp
    from d2d_link.channel import ChannelModel
    f = ChannelModel.grid(cfg)
    return LinkResponse(Waveform(p, cfg.dt), Waveform(p / amp / osr, cfg.dt),
                        ChannelModel(np.ones_like(f, dtype=complex), f), np.ones_like(f, dtype=complex), osr)


def _quiet():
    return LinkConfig(clocking=ClockingConfig(), rx=RxConfig(noise_rms_v=0.05), sim=SimConfig(stat_phase_points=32))


def test_no_isi_ber_is_q_of_snr():
    cfg = _quiet()
    r = run_statistical(cfg, _flat_response(cfg, 0.2))
    assert r.ber == pytest.approx(float(qfunc(0.2 / 0.05)), rel=1e-6)
    assert r.extras["n_cursors"] == 0


def test_no_isi_eye_height_at_target():
    cfg = dataclasses.replace(_quiet(), rx=RxConfig(noise_rms_v=0.01))
    r = run_statistical(cfg, _flat_response(cfg, 0.2))
    q_inv = np.sqrt(2.0) * erfcinv(2.0 * r.target_ber)      # Q^-1(target)
    assert r.eye_height_v == pytest.approx(2.0 * (0.2 - q_inv * 0.01), rel=1e-4)
    assert r.eye_width_ui == pytest.approx(1.0, abs=0.04)


def test_jitter_only_closed_form():
    """A rectangular eye with a jittered sampler: an error needs the sample to
    land in the neighbour (|delta| > 0.5 UI) and the neighbour to differ."""
    cfg = LinkConfig(clocking=ClockingConfig(data_path_rj_s=0.2 * 31.25e-12),   # 0.2 UI RMS
                     rx=RxConfig(noise_rms_v=1e-9, sampling_phase_ui=0.0),
                     sim=SimConfig(stat_phase_points=32, stat_jitter_sigmas=12.0))
    r = run_statistical(cfg, _flat_response(cfg, 0.2))
    expect = 0.5 * 2.0 * float(qfunc(0.5 / 0.2))
    assert r.ber == pytest.approx(expect, rel=0.03)


def test_single_postcursor_closed_form():
    m, c, s = 0.2, 0.05, 0.03
    model = isi_model(np.array([m, c]), 0, bin_v=0.0125)        # the cursor is a whole number of bins
    assert model.n_cursors == 1 and model.sigma_isi_v == pytest.approx(c)
    p = tail_probability(model, s, 0.0)
    assert p == pytest.approx(0.5 * (qfunc((m - c) / s) + qfunc((m + c) / s)), rel=1e-9)
    # a fractional shift keeps the mean and the total probability exactly
    frac = isi_model(np.array([m, 0.0123, -0.0045]), 0, bin_v=1e-3)
    assert frac.pmf.sum() == pytest.approx(1.0, abs=1e-12) and float(frac.pmf @ frac.grid_v) == pytest.approx(0.0, abs=1e-15)


def test_isi_grid_converges_with_hundreds_of_crosstalk_cursors():
    """The case that broke the old 'enumerate the largest M' model: the middle
    lane of the x5 coupled module sees 349 cursors and its eye width moved
    0.613 / 0.671 / 0.683 UI with M = 8 / 12 / 16. On the voltage grid the
    only knob is the bin, and halving it must not move the eye."""
    from conftest import REPO
    from d2d_link.channel import link_response
    from d2d_link.clock.forwarded import ForwardedClock
    from d2d_link.engine.lanes import aggressors_of, lane_map, physical_skews_ps

    cfg = load_config(REPO / "configs" / "standard_32g_x5_coupled.yaml")
    cfg = dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, stat_phase_points=16))
    resp, clock = link_response(cfg), ForwardedClock(cfg)
    aggr = tuple((d, sk) for d, sk, _ in aggressors_of(cfg, lane_map(cfg), 2, physical_skews_ps(cfg)))
    out = {}
    for b in (1e-4, 5e-5):
        c = dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, stat_isi_bin_v=b))
        out[b] = StatisticalEngine(c, resp, clock, aggr).run(2)
    coarse, fine = out[1e-4], out[5e-5]
    assert fine.extras["n_cursors"] > 300 and fine.extras["isi_bins"] > coarse.extras["isi_bins"]
    assert abs(fine.eye_width_ui - coarse.eye_width_ui) < 0.002
    assert abs(fine.eye_height_v - coarse.eye_height_v) < 1e-3
    assert fine.eye_width_ui == pytest.approx(0.699, abs=0.01)      # 0.685 before the geometry-derived L / C (0.5.0); 0.671 with 12 cursors enumerated


def test_tails_live_in_the_log_domain():
    """1e-27 is 10.8 sigma; a lane's BER at its own eye centre is far below
    1e-308 and used to underflow to exactly 0.0 for every lane."""
    m = isi_model(np.array([0.2, 0.01]), 0, bin_v=1e-3)
    lt = log10_tail(m, 0.003, -0.1)                 # 100 sigma away
    assert np.isfinite(lt) and lt < -2000 and tail_probability(m, 0.003, -0.1) == 0.0
    assert log10_tail(m, 0.003, np.array([0.0, 0.1])).shape == (2,)
    cfg = LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, clock_path_rj_s=200e-15),
                     sim=SimConfig(stat_phase_points=16))
    r = run_statistical(cfg)
    assert np.isfinite(r.log10_ber) and r.log10_ber < -300 and r.ber == 0.0
    assert np.all(np.isfinite(r.bathtub_log10_ber)) and r.bathtub_log10_ber.max() > -1.0   # the neighbour, half a UI on
    assert "10^" in r.summary()


def test_eye_width_is_capped_at_one_ui():
    """A symbol's eye cannot be wider than the symbol: an opening wider than
    1 UI is clipped and flagged. The short unfiltered lines that read 1.008 to
    1.026 UI in the health check turn out to have been the log interpolation
    across the cliff beside the eye (0.994 UI with the edges found on the
    real bathtub, phase 3), so the cap is exercised on a forced opening."""
    import math
    from d2d_link.config import TxConfig

    cfg = LinkConfig(channel=ChannelConfig(length_mm=2.0), rx=RxConfig(noise_rms_v=3e-3), tx=TxConfig(bw_hz=math.inf),
                     sim=SimConfig(stat_phase_points=32))
    r = run_statistical(cfg)
    assert 0.98 < r.eye_width_ui < 1.0 and not r.extras["eye_width_clipped"]

    class Wide(StatisticalEngine):
        @staticmethod
        def eye_region(phases, log10_ber, target, refine=None):
            return (-0.62, 0.61)

    w = Wide(cfg).run()
    assert w.eye_width_ui == 1.0 and w.extras["eye_width_clipped"] and w.extras["eye_width_raw_ui"] == pytest.approx(1.23)
    assert "(clipped)" in w.summary() and w.phase_ui == pytest.approx(-0.005)
    ok = run_statistical(dataclasses.replace(cfg, channel=ChannelConfig(length_mm=25.0)))
    assert ok.eye_width_ui < 1.0 and not ok.extras["eye_width_clipped"] and "(clipped)" not in ok.summary()


def test_reaches_1e_minus_27_with_a_finite_eye():
    cfg = LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, clock_path_rj_s=200e-15),
                     sim=SimConfig(stat_phase_points=32))
    r = run_statistical(cfg)
    assert r.target_ber == 1e-27 and r.targets["ber"][1] == "survey"
    assert r.ber < 1e-27 and 0.0 < r.eye_height_v < 0.4 and 0.5 < r.eye_width_ui < 1.0
    assert r.passes


def test_eye_closes_with_noise_and_bathtub_is_symmetric_when_isi_free():
    cfg = _quiet()
    eng = StatisticalEngine(dataclasses.replace(cfg, rx=RxConfig(noise_rms_v=0.1)), _flat_response(cfg, 0.2))
    r = eng.run()
    assert r.eye_height_v == 0.0 and r.eye_width_ui == 0.0
    ber = r.bathtub_ber
    assert np.allclose(ber[1:-1], ber[1:-1][::-1], rtol=1e-6)   # the end points sit on the transition


def test_vref_offset_shrinks_one_side():
    cfg = dataclasses.replace(_quiet(), rx=RxConfig(noise_rms_v=0.01, vref_offset_v=0.03))
    eng = StatisticalEngine(cfg, _flat_response(cfg, 0.2))
    hi, lo = eng.half_eye(0.0, 1e-12, +1), eng.half_eye(0.0, 1e-12, -1)
    assert hi == pytest.approx(lo - 0.06, rel=1e-3)


def test_dcd_splits_the_sampling_phase():
    cfg = dataclasses.replace(_quiet(), clocking=ClockingConfig(dcd_ui=0.1))
    eng = StatisticalEngine(cfg, _flat_response(cfg, 0.2))
    ph = eng.sampling_phases(0.1)
    assert sorted(p for p, _ in ph) == pytest.approx([0.05, 0.15])
    assert sum(w for _, w in ph) == pytest.approx(1.0)


def test_jitter_quadrature_is_normalised_and_wide_enough():
    x, w = jitter_quadrature(0.009, 64, 12.0)
    assert w.sum() == pytest.approx(1.0) and x.max() >= 12 * 0.009
    assert x[1] - x[0] <= 0.009 / 4
    x0, w0 = jitter_quadrature(0.0, 64, 12.0)
    assert x0.tolist() == [0.0] and w0.tolist() == [1.0]


def test_bathtub_window_follows_the_eye_wherever_the_reference_sits():
    """An opening that reaches the +-0.5 UI window's edge extends the window
    by half a UI on that side (M3; it read half an eye before). A reference
    sample pushed 0.45 UI off the eye's centre -- what a flat-topped pulse
    did to the peak-sample reference three times -- must give the same eye,
    found 0.45 UI away. The BER is not periodic in the phase (one UI away the
    neighbour is sampled), so the search is a plain widest-opening search on
    the extended window."""
    from conftest import REPO
    from d2d_link.channel import link_response

    cfg = load_config(REPO / "configs" / "standard_32g_x1.yaml")
    cfg = dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, stat_phase_points=32))
    resp = link_response(cfg)

    class Shifted(LinkResponse):
        @property
        def main_index(self) -> int:
            return LinkResponse.main_index.fget(self) + int(round(0.45 * self.osr))

    shifted = Shifted(resp.pulse, resp.impulse, resp.channel, resp.H_total, resp.osr, resp.xtalk_pulses)
    r0, r = StatisticalEngine(cfg, resp).run(), StatisticalEngine(cfg, shifted).run()
    assert r0.bathtub_phase_ui[0] == -0.5 and r0.bathtub_phase_ui[-1] == 0.5
    assert r.bathtub_phase_ui[0] <= -1.0 + 1e-12 and r.bathtub_phase_ui[-1] == 0.5    # grown on the side the eye went
    assert r.eye_width_ui == pytest.approx(r0.eye_width_ui, abs=0.002)
    assert r.eye_height_v == pytest.approx(r0.eye_height_v, rel=0.01)
    assert r.phase_ui == pytest.approx(r0.phase_ui - 0.45, abs=0.02)
    # the milestone-1 link keeps its +-0.5 UI window and its numbers
    r1 = run_statistical(load_config(REPO / "configs" / "standard_32g_x1.yaml"))
    assert r1.bathtub_phase_ui[0] == -0.5 and r1.bathtub_phase_ui[-1] == 0.5 and r1.bathtub_ber.size == 65
    assert r1.eye_width_ui == pytest.approx(0.7741, abs=0.0005)


def test_eye_width_does_not_depend_on_the_phase_grid():
    """The eye's edges are found on the real bathtub (regula falsi), not
    interpolated between grid points: 16 and 128 phases per UI must agree.
    Log interpolation across the cliff beside the eye moved the width by
    2e-3 UI on a 16-point grid with the jitter kernel's reach (phase 3)."""
    from conftest import REPO

    cfg = load_config(REPO / "configs" / "standard_32g_x1.yaml")
    ew = {}
    for pts in (16, 128):
        r = run_statistical(dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, stat_phase_points=pts)))
        ew[pts] = (r.eye_width_ui, r.phase_ui, r.eye_height_v)
    assert ew[16][0] == pytest.approx(ew[128][0], abs=2e-4)
    assert ew[16][1] == pytest.approx(ew[128][1], abs=2e-4) and ew[16][2] == pytest.approx(ew[128][2], rel=1e-3)
    eng = StatisticalEngine(cfg)
    edge = eng.eye_edge(0.0, 0.5, 1e-27)
    assert eng.log10_error_probability(edge - 1e-4) <= -27.0 <= eng.log10_error_probability(edge + 1e-4)
