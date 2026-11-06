"""Phase 7: the receiver front end -- its bandwidth on the data edges, where
the noise is referred (the CTLE's noise cost), and link training's eye
centring at its own BER."""

import dataclasses
import math

import numpy as np
import pytest
from scipy.special import ndtr

from d2d_link.channel.model import link_response, noise_shaping_gain, rx_response, sampler_noise_rms_v
from d2d_link.config import ChannelConfig, ClockingConfig, CtleConfig, LinkConfig, RxConfig, SimConfig, TxConfig
from d2d_link.engine import run_statistical, run_time

F_N = LinkConfig().f_nyquist
QUIET = ClockingConfig()                 # no jitter at all: the noise alone sets the BER


def _rx(**kw) -> LinkConfig:
    return LinkConfig(rx=RxConfig(**kw))


def test_first_order_front_end_matches_the_closed_form():
    # white noise through one pole: integral |H|^2 df = pi bw / 2
    for bw in (16e9, 24e9, 48e9):
        g = noise_shaping_gain(_rx(noise_at="input", bw_hz=bw))
        assert g == pytest.approx(math.sqrt(math.pi * bw / (2.0 * F_N)), rel=1e-8)
    assert sampler_noise_rms_v(_rx(noise_rms_v=3e-3, noise_at="input", bw_hz=32e9)) == pytest.approx(3e-3 * math.sqrt(math.pi), rel=1e-8)


def test_sampler_referred_noise_is_untouched_and_the_front_end_flat_by_default():
    cfg = LinkConfig()
    assert noise_shaping_gain(cfg) == 1.0
    assert sampler_noise_rms_v(cfg) == cfg.rx.noise_rms_v
    f = np.linspace(0.0, 5e11, 8)
    assert np.all(rx_response(cfg, f) == 1.0)
    assert link_response(cfg).noise_impulse is None
    # with a pole but the noise still at the sampler, the pulse changes and the noise does not
    cfg2 = _rx(bw_hz=24e9)
    assert noise_shaping_gain(cfg2) == 1.0
    assert abs(rx_response(cfg2, np.array([24e9]))[0]) == pytest.approx(1.0 / math.sqrt(2.0))


def test_input_referred_noise_needs_a_bandwidth_and_training_ber_a_range():
    with pytest.raises(ValueError, match="rx.noise_at"):
        RxConfig(noise_at="input")
    with pytest.raises(ValueError, match="rx.training_ber"):
        RxConfig(training_ber=0.5)
    with pytest.raises(ValueError, match="rx.bw_hz"):
        RxConfig(bw_hz=0.0)


def test_ctle_peaking_costs_noise_once_its_poles_are_paid_for():
    # the behavioural CTLE has two poles and one zero: it is itself a lowpass,
    # so against a wide front end a little peaking still *saves* noise over
    # no CTLE at all; from there every dB of peaking costs noise
    def g(peak, bw=120e9):            # under the osr x f_N / 4 = 128 GHz cap
        return noise_shaping_gain(_rx(noise_at="input", bw_hz=bw, ctle=CtleConfig(enable=True, peak_db=peak)))

    off = noise_shaping_gain(_rx(noise_at="input", bw_hz=120e9))
    assert g(1.0) < off
    assert g(1.0) < g(3.0) < g(6.0) < g(9.0)


def test_front_end_pole_slows_the_pulse_and_the_input_referred_noise_shrinks_the_eye():
    base = LinkConfig(clocking=QUIET, sim=SimConfig(stat_phase_points=16))
    flat = run_statistical(base)
    pole = run_statistical(dataclasses.replace(base, rx=RxConfig(bw_hz=20e9)))
    assert pole.main_cursor_v < flat.main_cursor_v
    assert pole.eye_height_v < flat.eye_height_v
    # the same 2 mV, referred at the input of a 20 GHz front end, is 2.8 mV at the sampler
    inp = run_statistical(dataclasses.replace(base, rx=RxConfig(bw_hz=20e9, noise_at="input")))
    assert inp.sigma_noise_v == pytest.approx(pole.sigma_noise_v * math.sqrt(math.pi * 20e9 / (2 * F_N)), rel=1e-8)
    assert inp.eye_height_v < pole.eye_height_v
    assert inp.extras["noise_gain"] == pytest.approx(math.sqrt(math.pi * 20e9 / (2 * F_N)), rel=1e-8)
    assert inp.extras["sigma_noise_input_v"] == 2e-3


def test_time_engine_filters_the_input_noise_and_lands_on_the_integral():
    # a short clean line, no jitter: the BER is Q(main / sigma) with the ISI
    # a small correction; the waveform path really filters white noise
    # through the front end, so its sampled RMS is an independent measure of
    # the integral (band-limited to osr / (2 UI): a shade under)
    cfg = LinkConfig(channel=ChannelConfig(length_mm=1.0), tx=TxConfig(bw_hz=60e9), clocking=QUIET,
                     rx=RxConfig(noise_rms_v=0.045, noise_at="input", bw_hz=24e9),
                     sim=SimConfig(n_symbols=200_000, stat_phase_points=16))
    s = run_statistical(cfg)
    t = run_time(cfg, phase_ui=s.phase_ui)
    assert t.extras["noise_filtered"] is True
    assert t.n_errors >= 100
    assert 0.5 < t.ber / s.ber < 2.0
    sampled = t.samples - t.sample_bits * t.extras["main_cursor_v"]
    isi = s.extras["sigma_isi_v"]
    noise_rms = math.sqrt(max(float(np.var(sampled)) - isi * isi, 0.0))
    assert noise_rms == pytest.approx(s.sigma_noise_v, rel=0.03)
    assert 0.5 < t.ber / (1.0 - ndtr(t.extras["main_cursor_v"] / s.sigma_noise_v)) < 2.0
    # the samples mode has no waveform: the marginal sigma, the same BER within the statistics
    ts = run_time(cfg, phase_ui=s.phase_ui, mode="samples")
    assert ts.extras["noise_filtered"] is False
    assert ts.extras["sigma_noise_v"] == pytest.approx(s.sigma_noise_v)
    assert 0.5 < ts.ber / s.ber < 2.0


def test_training_centres_at_its_own_ber_and_the_lane_pays_the_offset():
    # a short line with the driver's pole has an asymmetric bathtub: where the
    # 1e-3 opening is centred is not where the 1e-27 opening is
    base = LinkConfig(channel=ChannelConfig(length_mm=25.0), clocking=QUIET,
                      rx=RxConfig(noise_rms_v=0.008), sim=SimConfig(stat_phase_points=32))
    ideal = run_statistical(base)
    assert ideal.extras["centre_offset_ui"] == 0.0
    trained = run_statistical(dataclasses.replace(base, rx=dataclasses.replace(base.rx, training_ber=1e-3)))
    off = trained.extras["centre_offset_ui"]
    assert off != 0.0 and abs(off) < 0.05
    assert trained.phase_ui == pytest.approx(ideal.phase_ui + off, abs=1e-9)
    assert trained.extras["training_centre_ui"] == pytest.approx(trained.phase_ui)
    # the symmetric opening around the trained sampling instant
    assert trained.eye_width_ui == pytest.approx(ideal.eye_width_ui - 2.0 * abs(off), abs=2e-4)
    assert trained.eye_height_v <= ideal.eye_height_v + 1e-6


def test_front_end_bandwidth_is_capped_by_the_waveform_grid():
    """The closed-form noise integral runs to infinity, the pulse and the time
    engine stop at osr x f_Nyquist: a 1 THz pole on the 32x grid put the two
    1.8x apart (second health check). A quarter of the grid's top is the limit."""
    with pytest.raises(ValueError, match="quarter of the waveform grid"):
        _rx(bw_hz=1e12)
    assert _rx(bw_hz=128e9).rx.bw_hz == 128e9
    LinkConfig(rx=RxConfig(bw_hz=256e9), sim=SimConfig(osr=64))
    with pytest.raises(ValueError, match="quarter"):
        LinkConfig(rx=RxConfig(bw_hz=129e9), sim=SimConfig(osr=32))


def test_training_window_follows_the_training_opening():
    """The bathtub window grows when the opening at the target BER reaches its
    edge; the training opening is wider and reached it first, so training
    was centred inside a window it overflowed (0.010 UI off on this 5 mm
    line). The window now grows for either opening."""
    from d2d_link.engine.statistical import StatisticalEngine

    cfg = LinkConfig(channel=ChannelConfig(length_mm=5.0), tx=TxConfig(bw_hz=60e9),
                     clocking=ClockingConfig(data_path_rj_s=100e-15), rx=RxConfig(training_ber=1e-3),
                     sim=SimConfig(stat_phase_points=32))
    r = run_statistical(cfg)
    eng = StatisticalEngine(cfg)
    wide = eng.eye_region(*eng.bathtub(-1.5, 1.5), 1e-3, refine=eng.eye_edge)
    assert r.extras["training_centre_ui"] == pytest.approx(0.5 * (wide[0] + wide[1]), abs=1e-3)
    assert r.bathtub_phase_ui[0] < -0.5 or r.bathtub_phase_ui[-1] > 0.5
    narrow = eng.eye_region(*eng.bathtub(-0.5, 0.5), 1e-3, refine=eng.eye_edge)
    assert abs(0.5 * (narrow[0] + narrow[1]) - r.extras["training_centre_ui"]) > 0.005


def test_eye_monitor_dwell_puts_a_statistical_error_on_the_centre():
    """0.15.7: training counts rx.training_dwell_symbols at each phase; the
    centre it finds is off by sigma ~ 1/sqrt(N p) (Poisson at the edges),
    and the lane is judged training_sigmas of it toward its nearer edge.
    100x the dwell is 10x less sigma; no dwell = exact edges, as before."""
    from d2d_link.config import LinkConfig, RxConfig, SimConfig
    from d2d_link.engine import run_statistical

    base = LinkConfig(rx=RxConfig(noise_rms_v=0.008, training_ber=1e-6), sim=SimConfig(stat_phase_points=16))
    exact = run_statistical(base)
    r7 = run_statistical(dataclasses.replace(base, rx=dataclasses.replace(base.rx, training_dwell_symbols=10_000_000)))
    r9 = run_statistical(dataclasses.replace(base, rx=dataclasses.replace(base.rx, training_dwell_symbols=1_000_000_000)))
    assert exact.extras["training_sigma_ui"] == 0.0
    assert r7.extras["training_sigma_ui"] == pytest.approx(10.0 * r9.extras["training_sigma_ui"], rel=1e-9)
    shift = r7.extras["training_centre_ui"] - exact.extras["training_centre_ui"]
    assert abs(shift) == pytest.approx(3.0 * r7.extras["training_sigma_ui"], rel=1e-9)
    assert r7.eye_width_ui <= exact.eye_width_ui
    with pytest.raises(ValueError, match="training_ber"):
        RxConfig(training_dwell_symbols=1000)
