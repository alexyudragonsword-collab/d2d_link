"""Invariant #4, milestone 2: lane-to-lane far-end crosstalk, the neighbours
the lane map leaves active, and the engines' agreement with it."""

import dataclasses

import numpy as np
import pytest

from conftest import PROFILE
from d2d_link.channel import link_response
from d2d_link.channel.model import xtalk_response
from d2d_link.config import ChannelConfig, ClockingConfig, LaneConfig, LinkConfig, RxConfig, SimConfig
from d2d_link.engine import run_link, run_statistical, run_time
from d2d_link.engine.lanes import aggressors_of, lane_map, physical_skews_ps

X = ChannelConfig(length_mm=25.0, xtalk="fext")


def test_xtalk_level_at_nyquist_and_off_by_default():
    cfg = LinkConfig(channel=X)
    f = np.array([cfg.f_nyquist])
    assert 20 * np.log10(abs(xtalk_response(cfg, f, 1)[0])) == pytest.approx(-30.0)   # standard preset
    assert 20 * np.log10(abs(xtalk_response(cfg, f, 2)[0])) == pytest.approx(-42.0)
    assert xtalk_response(cfg, f, 3)[0] == 0.0
    assert xtalk_response(LinkConfig(), f, 1)[0] == 0.0
    custom = LinkConfig(channel=dataclasses.replace(X, xtalk_adjacent_db=-20.0, xtalk_second_db=-25.0))
    assert custom.xtalk_db() == (-20.0, -25.0)
    with pytest.raises(ValueError):
        ChannelConfig(xtalk_adjacent_db=3.0)


def test_xtalk_pulses_and_cursors():
    r = link_response(LinkConfig(channel=X))
    assert set(r.xtalk_pulses) == {1, 2}
    c1 = r.xtalk_cursors(1, 0.0)
    c2 = r.xtalk_cursors(2, 0.0)
    assert c1.size > 0 and np.max(np.abs(c1)) > np.max(np.abs(c2)) > 0.0
    assert np.max(np.abs(c1)) < 0.1 * r.main_amplitude
    assert r.xtalk_cursors(3, 0.0).size == 0
    # a skewed aggressor is read at a shifted position: different cursors (the
    # FEXT pulse is a doublet, so its energy at the sampling instant swings
    # with the skew -- which is why skew is part of the crosstalk model)
    cs = r.xtalk_cursors(1, 0.0, rel_skew_ui=0.3)
    assert not np.allclose(cs[: min(cs.size, c1.size)], c1[: min(cs.size, c1.size)])
    assert cs.size > 0
    assert link_response(LinkConfig()).xtalk_cursors(1, 0.0).size == 0


def test_aggressors_follow_the_lane_map_and_skip_silent_lanes():
    cfg = LinkConfig(channel=X, lanes=LaneConfig(count=6, spare_count=2, failed=(2,), repair="spare",
                                                 skew_ps=(0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)))
    lm = lane_map(cfg)
    sk = physical_skews_ps(cfg)
    assert lm.logical_to_physical == (0, 1, 3, 4, 5, 6)
    a1 = aggressors_of(cfg, lm, 1, sk)
    assert [(d, q) for d, _, q in a1] == [(1, 0), (2, 3)]        # lane 2 is dead, lane 3 is two away
    a7 = aggressors_of(cfg, lm, 6, sk)
    assert [(d, q) for d, _, q in a7] == [(2, 4), (1, 5)]        # spare 7 is unused and silent
    assert a1[1][1] == pytest.approx(2e-12 / cfg.ui)             # 3 ps - 1 ps relative skew
    assert aggressors_of(LinkConfig(lanes=LaneConfig(count=4)), lane_map(LinkConfig(lanes=LaneConfig(count=4))),
                         1, np.zeros(4)) == ()


def test_middle_lane_sees_more_crosstalk_than_the_edge():
    cfg = LinkConfig(channel=X, lanes=LaneConfig(count=5), clocking=ClockingConfig(pll_profile=PROFILE),
                     sim=SimConfig(stat_phase_points=16))
    res = run_link(cfg)
    n = [r.extras["n_aggressors"] for r in res.stat]
    assert n == [2, 3, 4, 3, 2]
    eh = [r.eye_height_v for r in res.stat]
    assert eh[2] < eh[0] and eh[2] < eh[4]
    alone = run_link(dataclasses.replace(cfg, channel=dataclasses.replace(X, xtalk="none"))).stat
    assert all(a.eye_height_v > r.eye_height_v for a, r in zip(alone, res.stat))


def test_single_lane_is_untouched_by_crosstalk_settings():
    a = run_statistical(LinkConfig(channel=X, sim=SimConfig(stat_phase_points=16)))
    b = run_statistical(LinkConfig(channel=dataclasses.replace(X, xtalk="none"), sim=SimConfig(stat_phase_points=16)))
    assert a.ber == b.ber and a.eye_height_v == b.eye_height_v


def test_engines_agree_with_strong_crosstalk():
    cfg = LinkConfig(channel=dataclasses.replace(X, xtalk_adjacent_db=-14.0),
                     lanes=LaneConfig(count=3, skew_ps=(0.0, 3.0, -2.0)),
                     clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, clock_path_rj_s=200e-15),
                     rx=RxConfig(noise_rms_v=0.045),
                     sim=SimConfig(n_symbols=300_000, engine="both", stat_phase_points=32))
    res = run_link(cfg)
    assert all(t.n_errors >= 40 for t in res.time)
    for ratio in res.consistency_ratios():
        assert 0.5 < ratio < 2.0, res.consistency_ratios()
    # the middle lane carries both neighbours; the edges one each
    assert [r.extras["n_aggressors"] for r in res.stat] == [2, 2, 2]   # x3: every lane sees the other two
    assert all(r.extras["xtalk_rms_v"] > 0 for r in res.stat)


def test_time_engine_takes_aggressors_directly():
    cfg = LinkConfig(channel=dataclasses.replace(X, xtalk_adjacent_db=-12.0), rx=RxConfig(noise_rms_v=0.04),
                     sim=SimConfig(n_symbols=100_000))
    quiet = run_time(cfg, phase_ui=0.0)
    loud = run_time(cfg, phase_ui=0.0, aggressors=((1, 0.0, 7), (1, 0.2, 8)))
    assert loud.extras["n_aggressors"] == 2 and loud.n_errors > quiet.n_errors
