"""Milestone 3: the coupled-line crosstalk estimate and the budget report."""

import dataclasses
import importlib.util
import json

import numpy as np
import pytest

from conftest import PROFILE, REPO
from d2d_link.channel.coupled import (coupling_fraction, describe, eps_eff_microstrip, fext_db, fext_ratio_at,
                                      trace_pitch_um)
from d2d_link.config import ChannelConfig, ClockingConfig, LaneConfig, LinkConfig, PackageConfig, SimConfig
from d2d_link.config.schema import PACKAGE_STACKUP
from d2d_link.engine import run_link

COUPLED = ChannelConfig(length_mm=25.0, xtalk="coupled")


def test_pitch_comes_from_the_survey_table_unless_configured():
    pitch, src = trace_pitch_um(LinkConfig(channel=COUPLED))
    assert pitch == pytest.approx(115.0) and src == "survey"        # midpoint of 100..130 um
    pitch, src = trace_pitch_um(LinkConfig(package=PackageConfig(kind="advanced"), channel=COUPLED))
    assert pitch == pytest.approx(40.0) and src == "survey"
    pitch, src = trace_pitch_um(LinkConfig(channel=dataclasses.replace(COUPLED, trace_pitch_um=80.0)))
    assert pitch == 80.0 and src == "config"


def test_effective_permittivity_bounds():
    e = eps_eff_microstrip(3.5, 20.0, 30.0)
    assert 1.0 < e < 3.5
    assert eps_eff_microstrip(3.5, 2000.0, 1.0) == pytest.approx(3.5, rel=0.01)   # a very wide trace: all in the dielectric
    assert eps_eff_microstrip(1.0, 20.0, 30.0) == pytest.approx(1.0)


def test_coupling_falls_with_spacing_and_grows_with_length():
    cfg = LinkConfig(channel=COUPLED)
    assert coupling_fraction(115.0, 30.0) > coupling_fraction(230.0, 30.0) > 0.0
    adj, sec = fext_db(cfg)
    assert sec < adj < 0.0
    short = fext_db(LinkConfig(channel=dataclasses.replace(COUPLED, length_mm=5.0)))[0]
    assert short < adj                                                  # a shorter coupled run: less FEXT
    r25, r5 = fext_ratio_at(cfg, 115.0), fext_ratio_at(dataclasses.replace(cfg, channel=dataclasses.replace(COUPLED, length_mm=5.0)), 115.0)
    assert r25 == pytest.approx(5.0 * r5, rel=1e-9)                     # linear in length below the cap


def test_coupled_length_is_explicit_with_a_touchstone_channel():
    """A Touchstone file carries no routed length; the estimate needs one."""
    with pytest.raises(ValueError, match="coupled_length_mm"):
        ChannelConfig(kind="touchstone", file="x.s4p", xtalk="coupled")
    ok = ChannelConfig(kind="touchstone", file="x.s4p", xtalk="coupled", coupled_length_mm=12.0)
    assert LinkConfig(channel=ok).coupled_length_mm() == 12.0
    # on an analytic line the coupled length defaults to the line's length and may be shortened
    cfg = LinkConfig(channel=COUPLED)
    assert cfg.coupled_length_mm() == 25.0
    half = LinkConfig(channel=dataclasses.replace(COUPLED, coupled_length_mm=12.5))
    assert fext_ratio_at(half, 115.0) == pytest.approx(0.5 * fext_ratio_at(cfg, 115.0), rel=1e-9)
    d = describe(half)
    assert d["coupled_length_mm"] == 12.5 and d["stackup_source"] == "model" and d["eps_eff"] == pytest.approx(cfg.rlgc()["eps_eff"])
    assert describe(LinkConfig(channel=dataclasses.replace(COUPLED, eps_r=3.0)))["stackup_source"] == "config"


def test_homogeneous_dielectric_couples_no_fext():
    # eps_eff == eps_r (a stripline at this order): the odd and even modes travel together
    cfg = LinkConfig(channel=dataclasses.replace(COUPLED, trace_width_um=1e6, dielectric_height_um=1.0))
    assert fext_db(cfg)[0] < -100.0


def test_cap_and_explicit_stackup():
    cfg = LinkConfig(channel=dataclasses.replace(COUPLED, length_mm=500.0, dielectric_height_um=200.0))
    assert fext_ratio_at(cfg, 115.0) == pytest.approx(1.0 / np.sqrt(2.0))
    st = LinkConfig(channel=dataclasses.replace(COUPLED, eps_r=4.0)).stackup()
    assert st["eps_r"] == 4.0 and st["trace_width_um"] == PACKAGE_STACKUP["standard"]["trace_width_um"]
    with pytest.raises(ValueError):
        ChannelConfig(eps_r=0.5)


def test_coupled_mode_feeds_the_lane_model():
    cfg = LinkConfig(channel=COUPLED, lanes=LaneConfig(count=3), clocking=ClockingConfig(pll_profile=PROFILE),
                     sim=SimConfig(stat_phase_points=16))
    assert cfg.xtalk_db() == fext_db(cfg)
    res = run_link(cfg)
    assert res.stat[1].extras["xtalk_rms_v"] > 0.0
    d = describe(cfg)
    assert d["pitch_source"] == "survey" and d["fext_adjacent_db"] == pytest.approx(cfg.xtalk_db()[0])
    # the standard package at its survey reach: the estimate is stronger than the behavioural preset
    assert fext_db(cfg)[0] > -30.0


@pytest.fixture(scope="module")
def budget_tool():
    spec = importlib.util.spec_from_file_location("budget_report", REPO / "tools" / "budget_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_budget_report_markdown_and_json(budget_tool, tmp_path):
    cfg = LinkConfig(channel=COUPLED, lanes=LaneConfig(count=2, skew_ps=(0.0, 2.0), deskew_step_ps=1.0),
                     clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=200e-15, track_bw_hz=2e6,
                                             pi_step_ui=1 / 64),
                     sim=SimConfig(stat_phase_points=16))
    rep = budget_tool.build(cfg)
    md = budget_tool.to_markdown(rep)
    for needle in ("# Timing budget", "## Clock-path jitter", "## Targets", "source: survey", "## Lanes", "| 1 | 1 |"):
        assert needle in md, needle
    terms = {r["term"]: r for r in rep["jitter_budget"]}
    total = terms["total (power sum)"]["fs"]
    assert total == pytest.approx(np.sqrt(sum(r["fs"] ** 2 for n, r in terms.items() if not n.startswith("total"))))
    assert terms["phase-interpolator quantisation (uniform)"]["fs"] > 0.0
    assert rep["crosstalk"]["mode"] == "coupled" and rep["crosstalk"]["pitch_source"] == "survey"
    json.loads(json.dumps(rep))                                         # serialisable
    out = tmp_path / "b.md"
    assert budget_tool.main([str(REPO / "configs" / "standard_32g_x1.yaml"), "-o", str(out),
                             "--json", str(tmp_path / "b.json")]) == 0
    assert out.exists() and (tmp_path / "b.json").exists()


def test_sensitivity_report_names_the_deciding_guesses(budget_tool):
    """Every model preset and survey number the verdict leans on is perturbed;
    a target set just inside the nominal eye is flipped by the loss knobs."""
    from d2d_link.config import TargetConfig

    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0), clocking=ClockingConfig(pll_profile=PROFILE),
                     sim=SimConfig(stat_phase_points=16),
                     target=TargetConfig(eye_height_mv=215.0))              # 222 mV nominal: 20 % more skin loss (203) closes it
    sens = budget_tool.sensitivity(cfg)
    labels = {r["label"]: r for r in sens["rows"]}
    assert {"rdc_ohm_m", "r_skin", "loss_tangent", "z0_ohm", "target.eye_height_mv", "target.eye_width_ui"} <= set(labels)
    assert "trace_pitch_um" not in labels                                   # one lane: no crosstalk knobs
    assert labels["r_skin"]["source"] == "model" and labels["target.eye_width_ui"]["source"] == "survey"
    assert labels["target.eye_height_mv"]["source"] == "config"
    assert sens["nominal"]["passes"] and labels["r_skin"]["flips"] and labels["target.eye_height_mv"]["flips"]
    assert labels["r_skin"]["high"]["passes"] is False and labels["r_skin"]["low"]["passes"] is True
    assert labels["z0_ohm"]["low"]["passes"] is False                      # 40 ohm into 50 ohm terminations: reflections
    assert not labels["rdc_ohm_m"]["flips"]                                # DC resistance does not decide anything
    md = budget_tool.sensitivity_markdown(sens)
    assert "Verdict-deciding:" in md and "r_skin" in md
    coupled = LinkConfig(channel=COUPLED, lanes=LaneConfig(count=3), sim=SimConfig(stat_phase_points=16))
    knobs = {k["label"]: k for k in budget_tool.sensitivity_knobs(coupled)}
    assert {"trace_pitch_um", "eps_r", "dielectric_height_um", "trace_width_um"} <= set(knobs)
    assert knobs["trace_pitch_um"]["source"] == "survey" and knobs["eps_r"]["source"] == "model"

