"""Invariant #4: lanes, skew, the shared clock and repair are configuration."""

import dataclasses

import numpy as np
import pytest

from conftest import PROFILE, REPO
from d2d_link.config import ClockingConfig, LaneConfig, LinkConfig, SimConfig, load_config
from d2d_link.engine import lane_map, run_link
from d2d_link.engine.lanes import physical_skews_ps, residual_skew_ui


def test_no_repair_reports_the_dead_lane():
    lm = lane_map(LinkConfig(lanes=LaneConfig(count=4, failed=(2,))))
    assert lm.logical_to_physical == (0, 1, 2, 3) and lm.unrepaired == (2,) and not lm.link_up


def test_spare_repair_remaps_around_the_failure():
    lm = lane_map(LinkConfig(lanes=LaneConfig(count=4, spare_count=2, failed=(1, 4), repair="spare")))
    assert lm.logical_to_physical == (0, 2, 3, 5) and lm.link_up and not lm.degraded


def test_spare_repair_runs_out():
    lm = lane_map(LinkConfig(lanes=LaneConfig(count=2, spare_count=1, failed=(0, 1), repair="spare")))
    assert not lm.link_up and lm.unrepaired


def test_width_degrade_keeps_the_intact_half():
    lm = lane_map(LinkConfig(lanes=LaneConfig(count=16, failed=(5,), repair="width_degrade")))
    assert lm.active_width == 8 and lm.logical_to_physical == tuple(range(8, 16)) and lm.degraded
    lm2 = lane_map(LinkConfig(lanes=LaneConfig(count=16, failed=(3, 12), repair="width_degrade")))
    assert lm2.active_width == 4 and lm2.logical_to_physical == tuple(range(4, 8))
    lm3 = lane_map(LinkConfig(lanes=LaneConfig(count=16, repair="width_degrade")))
    assert lm3.active_width == 16 and not lm3.degraded


def test_skews_explicit_random_and_residual():
    cfg = LinkConfig(lanes=LaneConfig(count=3, skew_ps=(1.0, -2.0), deskew_step_ps=1.5))
    assert physical_skews_ps(cfg).tolist() == [1.0, -2.0, 0.0]
    assert residual_skew_ui(cfg, 1.0) == pytest.approx(-0.5e-12 / cfg.ui)
    assert residual_skew_ui(dataclasses.replace(cfg, lanes=LaneConfig(count=3)), 7.0) == 0.0
    # a per-lane tracker follows a static offset exactly: nothing is left but the PI step
    tracked = dataclasses.replace(cfg, clocking=ClockingConfig(track_bw_hz=2e6, pi_step_ui=1 / 32))
    assert residual_skew_ui(tracked, 1.0) == 0.0 and residual_skew_ui(cfg, 1.0, tracked=True) == 0.0
    assert residual_skew_ui(tracked, 1.0, tracked=False) == pytest.approx(-0.5e-12 / cfg.ui)
    r = LinkConfig(lanes=LaneConfig(count=8, skew_sigma_ps=2.0, skew_seed=3))
    a, b = physical_skews_ps(r), physical_skews_ps(r)
    assert np.array_equal(a, b) and a.std() > 0.5


def test_single_lane_is_lane_zero_of_a_module():
    sim = SimConfig(stat_phase_points=16)
    ck = ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, clock_path_rj_s=200e-15)
    one = run_link(LinkConfig(lanes=LaneConfig(count=1), clocking=ck, sim=sim))
    four = run_link(LinkConfig(lanes=LaneConfig(count=4), clocking=ck, sim=sim))
    assert len(one.stat) == 1 and len(four.stat) == 4
    assert four.stat[0].ber == one.stat[0].ber and four.stat[0].eye_height_v == one.stat[0].eye_height_v


def test_residual_skew_moves_the_lane_off_centre():
    sim = SimConfig(stat_phase_points=16)
    ck = ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, clock_path_rj_s=200e-15)
    res = run_link(LinkConfig(lanes=LaneConfig(count=2, skew_ps=(0.0, 6.0), deskew_step_ps=20.0),
                              clocking=ck, sim=sim))
    assert res.stat[1].skew_residual_ui == pytest.approx(6e-12 / res.cfg.ui)
    # off centre, the lane has only the symmetric opening around its sampling
    # instant (the eye height need not drop: a driver pole skews the pulse so
    # the height peaks later than the width's centre)
    assert res.stat[1].eye_width_ui < res.stat[0].eye_width_ui - 0.1 and res.stat[1].margin < res.stat[0].margin


def test_worst_lane_is_the_one_with_the_smallest_margin():
    """Every lane's BER at its own eye centre is below float resolution at a
    1e-27 target; ranking by it picked lane 0 every time (phase-0 finding)."""
    sim = SimConfig(stat_phase_points=16)
    ck = ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, clock_path_rj_s=200e-15)
    res = run_link(LinkConfig(lanes=LaneConfig(count=2, skew_ps=(0.0, 6.0), deskew_step_ps=20.0),
                              clocking=ck, sim=sim))
    assert res.worst.lane == 1 and res.worst.margin < res.stat[0].margin
    assert res.stat[0].ber == 0.0 == res.stat[1].ber                 # the number that could not rank them
    assert res.log10_ber_worst == max(r.log10_ber for r in res.stat) and res.ber_worst == 0.0
    assert res.eye_width_min_ui == res.stat[1].eye_width_ui


def test_tracked_lanes_keep_no_static_skew():
    """With a per-lane tracker the deskew residual is DC to the loop and is
    followed exactly; the two lanes are then identical but for the PI step,
    which both carry (earlier versions counted the residual and the step)."""
    sim = SimConfig(stat_phase_points=16)
    ck = ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, clock_path_rj_s=200e-15,
                        track_bw_hz=2e6, pi_step_ui=1 / 64)
    res = run_link(LinkConfig(lanes=LaneConfig(count=2, skew_ps=(0.0, 6.0), deskew_step_ps=20.0),
                              clocking=ck, sim=sim))
    assert res.stat[1].skew_residual_ui == 0.0 and res.stat[1].phase_ui == res.stat[0].phase_ui
    assert res.stat[1].eye_height_v == res.stat[0].eye_height_v and res.stat[1].extras["quantisation_ui"] == 1 / 64


def test_bundled_repair_configs():
    cfg = load_config(REPO / "configs" / "standard_32g_x16_repair.yaml")
    cfg = dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, stat_phase_points=16))
    res = run_link(cfg)
    assert res.lanes.active_width == 8 and len(res.stat) == 8 and res.lanes.link_up
    assert "repair width_degrade" in res.summary()
    adv = load_config(REPO / "configs" / "advanced_32g_x64_spare.yaml")
    lm = lane_map(adv)
    assert lm.active_width == 64 and 12 not in lm.logical_to_physical and 40 not in lm.logical_to_physical
