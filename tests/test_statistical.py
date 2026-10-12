"""Statistical engine: closed forms and the 1e-27 reach."""

import dataclasses

import numpy as np
import pytest
from scipy.special import erfcinv

from conftest import PROFILE
from d2d_link.channel.model import LinkResponse
from d2d_link.config import ChannelConfig, ClockingConfig, LinkConfig, RxConfig, SimConfig
from d2d_link.engine.statistical import (StatisticalEngine, isi_model, jitter_quadrature, qfunc,
                                         run_statistical, tail_probability)
from d2d_link.vendor.halo.waveform import Waveform


def _flat_response(cfg: LinkConfig, amp: float) -> LinkResponse:
    """An ideal 1-UI rectangular pulse of height ``amp``: no ISI at all."""
    osr = cfg.sim.osr
    p = np.zeros(8 * osr)
    p[2 * osr:3 * osr] = amp
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
    model = isi_model(np.array([m, c]), 0, n_enum=4)
    p = tail_probability(model, s, 0.0)
    assert p == pytest.approx(0.5 * (qfunc((m - c) / s) + qfunc((m + c) / s)), rel=1e-9)


def test_enumeration_vs_variance_agree_when_cursors_are_small():
    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0), rx=RxConfig(noise_rms_v=0.04),
                     sim=SimConfig(stat_enumerate_cursors=16, stat_phase_points=32))
    a = run_statistical(cfg).ber
    b = run_statistical(dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, stat_enumerate_cursors=10))).ber
    assert a == pytest.approx(b, rel=0.05)


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
