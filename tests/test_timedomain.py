"""Time engine: it counts what the statistics predict, chunk by chunk."""

import dataclasses

import numpy as np
import pytest

from conftest import PROFILE
from d2d_link.config import ChannelConfig, ClockingConfig, LinkConfig, RxConfig, SimConfig
from d2d_link.engine import run_time
from d2d_link.engine.statistical import qfunc


def test_quiet_link_has_no_errors():
    cfg = LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE), sim=SimConfig(n_symbols=50_000))
    r = run_time(cfg, phase_ui=0.0)
    assert r.n_errors == 0 and r.eye_height_sampled_v > 0.1
    assert r.eye_traces.shape[1] == cfg.sim.osr + 1


def test_awgn_ber_matches_q_on_a_short_line():
    cfg = LinkConfig(channel=ChannelConfig(length_mm=1.0), rx=RxConfig(noise_rms_v=0.07),
                     sim=SimConfig(n_symbols=300_000, pattern="random"))
    r = run_time(cfg, phase_ui=0.0)
    assert r.n_errors > 100
    assert r.ber == pytest.approx(float(qfunc(r.extras["main_cursor_v"] / 0.07)), rel=0.3)


def test_chunking_does_not_change_the_result():
    base = LinkConfig(channel=ChannelConfig(length_mm=25.0), rx=RxConfig(noise_rms_v=0.05),
                      clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=1e-12),
                      sim=SimConfig(n_symbols=60_000, chunk_symbols=60_000))
    a = run_time(base, phase_ui=-0.02)
    small = dataclasses.replace(base, sim=dataclasses.replace(base.sim, chunk_symbols=7_000))
    b = run_time(small, phase_ui=-0.02)
    assert a.n_errors == b.n_errors and a.n_errors > 20
    assert np.allclose(a.samples, b.samples, atol=1e-9)   # the FFT's rounding differs per block size


def test_sampler_sees_the_budgeted_jitter():
    cfg = LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=400e-15, clock_path_rj_s=300e-15),
                     sim=SimConfig(n_symbols=200_000))
    r = run_time(cfg, phase_ui=0.0)
    assert r.jitter_rms_s == pytest.approx(500e-15, rel=0.03)


def test_prbs_patterns_run():
    for pat in ("prbs15", "prbs31", "random"):
        cfg = LinkConfig(sim=SimConfig(n_symbols=5_000, pattern=pat))
        r = run_time(cfg, phase_ui=0.0)
        assert r.n_symbols == 5_000 and abs(r.sample_bits.mean()) < 0.1


def test_samples_mode_is_the_waveform_path_without_the_waveform():
    """``sim.time_mode: samples`` sums the interpolated cursors per symbol:
    the same arithmetic as sampling the convolved waveform, so the same
    errors to floating-point rounding; the only approximation is the cursor
    floor, which on a lossy line keeps every cursor (the tail of a 25 mm
    trace stays above 1e-6 of the main cursor for 130 UI)."""
    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0), rx=RxConfig(noise_rms_v=0.05),
                     clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=1e-12),
                     sim=SimConfig(n_symbols=100_000))
    a = run_time(cfg, phase_ui=-0.02)
    b = run_time(cfg, phase_ui=-0.02, mode="samples")
    assert a.n_errors == b.n_errors > 50 and b.extras["mode"] == "samples"
    assert np.allclose(a.samples, b.samples, atol=1e-9) and b.eye_traces.shape == (0, cfg.sim.osr + 1)
    assert b.jitter_rms_s == a.jitter_rms_s and b.extras["n_cursors_used"] >= 100
    # the config field drives run_link too, and the chunk size does not matter
    c = dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, time_mode="samples", chunk_symbols=7_000))
    d = run_time(c, phase_ui=-0.02)
    assert d.n_errors == a.n_errors and np.allclose(d.samples, a.samples, atol=1e-9)


def test_samples_mode_with_aggressors_and_a_cursor_floor():
    """Crosstalk lanes go through the same cursor sums; a loose cursor floor
    on a short advanced-package line drops most of the pulse's tail and
    changes a sample by no more than the dropped cursors' sum."""
    from d2d_link.config import LaneConfig, PackageConfig
    from d2d_link.engine import run_link

    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0, xtalk="fext", xtalk_adjacent_db=-14.0),
                     lanes=LaneConfig(count=3, skew_ps=(0.0, 3.0, -2.0)), rx=RxConfig(noise_rms_v=0.045),
                     clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15),
                     sim=SimConfig(n_symbols=60_000, engine="both", stat_phase_points=16))
    wave = run_link(cfg)
    samp = run_link(dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, time_mode="samples")))
    assert [t.n_errors for t in wave.time] == [t.n_errors for t in samp.time]
    assert all(np.allclose(w.samples, s.samples, atol=1e-9) for w, s in zip(wave.time, samp.time))
    short = LinkConfig(package=PackageConfig(kind="advanced"), channel=ChannelConfig(length_mm=2.0),
                       rx=RxConfig(noise_rms_v=0.05), clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=1e-12),
                       sim=SimConfig(n_symbols=50_000, time_cursor_floor=1e-4))
    full = run_time(short, phase_ui=0.0, mode="samples", )
    loose = run_time(dataclasses.replace(short, sim=dataclasses.replace(short.sim, time_cursor_floor=1e-4)), phase_ui=0.0,
                     mode="samples")
    exact = run_time(dataclasses.replace(short, sim=dataclasses.replace(short.sim, time_cursor_floor=0.0)), phase_ui=0.0,
                     mode="samples")
    assert loose.extras["n_cursors_used"] < exact.extras["n_cursors_used"]
    assert np.max(np.abs(loose.samples - exact.samples)) < 1e-4 * exact.extras["main_cursor_v"] * exact.extras["n_cursors_used"]
    assert abs(loose.n_errors - exact.n_errors) <= 2 and full.n_errors == loose.n_errors
