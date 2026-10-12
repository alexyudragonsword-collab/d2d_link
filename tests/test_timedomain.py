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
