"""Eye-width attribution (report.attribution, example 12, 0.13.8)."""

import dataclasses

import pytest

from conftest import PROFILE, REPO
from d2d_link.config import ChannelConfig, ClockingConfig, LaneConfig, LinkConfig, SimConfig
from d2d_link.report import attribution, attribution_causes, attribution_markdown, shapley, switched_off


def test_shapley_shares_sum_to_the_gap_and_split_interactions_evenly():
    # a + b alone gain 1 and 2, together 5: the interaction 2 is split evenly
    v = {frozenset(): 0.0, frozenset("a"): 1.0, frozenset("b"): 2.0, frozenset("ab"): 5.0}
    s = shapley(("a", "b"), lambda S: v[frozenset(S)])
    assert s == pytest.approx({"a": 2.0, "b": 3.0}) and sum(s.values()) == pytest.approx(5.0)


def test_attribution_switches_each_cause_off_and_its_shares_close_the_gap():
    cfg = LinkConfig(channel=ChannelConfig(length_mm=10.0, xtalk="fext"), lanes=LaneConfig(count=3),
                     clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, track_bw_hz=2e6,
                                             pi_step_ui=1 / 32),
                     sim=SimConfig(stat_phase_points=16))
    assert attribution_causes(cfg) == ("crosstalk", "jitter", "PI step")
    assert attribution_causes(LinkConfig()) == ("jitter",)
    off = switched_off(cfg, {"crosstalk", "jitter", "PI step"})
    assert off.channel.xtalk == "none" and off.clocking.pll_profile is None and off.pi_step_ui == 0.0
    a = attribution(cfg)
    assert len(a["subsets"]) == 8
    assert sum(a["share_ui"].values()) == pytest.approx(a["ideal_ui"] - a["full_ui"], abs=1e-12)
    assert a["ideal_ui"] > a["full_ui"] and all(a["alone_off_ui"][i] >= a["full_ui"] - 1e-9 for i in a["causes"])
    md = attribution_markdown(a)
    assert "| jitter |" in md and "| crosstalk |" in md
    assert "crosstalk" not in attribution_causes(dataclasses.replace(cfg, lanes=LaneConfig(count=1)))


def test_x1_sensitivity_numbers_the_docs_quote():
    """ROADMAP P1 #1 and cairn/spec-sources.md quote the x1 sensitivity:
    +0.091 nominal, nothing flips, the nearest sides the 0.70 UI target
    (+0.013) and the PLL profile 3 dB up (+0.029). Example 13 prints the
    same for every bundled config (the module ones take minutes); x1 is the
    one cheap enough for the suite (~15 s). Before 0.14.2 no test or
    expected output produced these numbers (fourth health check)."""
    from d2d_link.config import load_config
    from d2d_link.report import sensitivity

    s = sensitivity(load_config(REPO / "configs" / "standard_32g_x1.yaml"))
    assert s["nominal"]["passes"] and s["nominal"]["margin"] == pytest.approx(0.0909, abs=5e-4)
    assert not any(r["flips"] for r in s["rows"])
    rows = {r["label"]: r for r in s["rows"]}
    assert rows["target.eye_width_ui"]["high"]["margin"] == pytest.approx(0.013, abs=1e-3)
    assert rows["pll_shift_db"]["high"]["margin"] == pytest.approx(0.029, abs=1e-3)
    sides = sorted(r[k]["margin"] for r in s["rows"] for k in ("low", "high"))
    assert sides[0] == rows["target.eye_width_ui"]["high"]["margin"]          # the nearest side is the target's
