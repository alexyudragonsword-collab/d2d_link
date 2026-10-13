"""Invariant #1: one frozen, strict, round-tripping config; the form declares every field."""

import dataclasses

import pytest
import yaml

from conftest import REPO
from d2d_link.config import (ChannelConfig, ClockingConfig, LaneConfig, LinkConfig, SimConfig,
                             apply_overrides, dump_config, load_config)
from d2d_link.config.form import FIELDS, config_to_values, schema_paths, values_to_overrides
from d2d_link.config.schema import PACKAGE_RLGC


def test_defaults_are_the_milestone_link():
    cfg = LinkConfig()
    assert cfg.data_rate_gtps == 32.0 and cfg.lanes.count == 1
    assert cfg.clocking.scheme == "forwarded_ddr"
    assert cfg.forwarded_clock_hz == pytest.approx(16e9)
    assert cfg.ui == pytest.approx(31.25e-12)
    assert cfg.dt == pytest.approx(cfg.ui / 32)


def test_frozen():
    cfg = LinkConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.data_rate_gtps = 16.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.lanes.count = 4


def test_bundled_configs_load_and_roundtrip(tmp_path):
    for p in sorted((REPO / "configs").glob("*.yaml")):
        cfg = load_config(p)
        out = tmp_path / p.name
        dump_config(cfg, out)
        assert load_config(out) == cfg, p.name


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("data_rate_gtps: 32\nclocking:\n  rx_pll_profile: x.yaml\n")
    with pytest.raises(KeyError, match="rx_pll_profile"):
        load_config(p)


def test_yaml_exponent_strings_are_coerced(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("clocking:\n  data_path_rj_s: 200.0e-15\ntarget:\n  ber: 1e-27\n")
    cfg = load_config(p)
    assert cfg.clocking.data_path_rj_s == pytest.approx(200e-15)
    assert cfg.target.ber == pytest.approx(1e-27)


def test_overrides_group_per_dataclass():
    cfg = LinkConfig()
    c2 = apply_overrides(cfg, {"lanes.count": 4, "lanes.skew_ps": [1.0, 2.0, 3.0, 4.0],
                               "clocking.track_bw_hz": 1e6})
    assert c2.lanes.count == 4 and c2.lanes.skew_ps == (1.0, 2.0, 3.0, 4.0)
    assert c2.clocking.track_bw_hz == 1e6
    assert cfg.lanes.count == 1
    with pytest.raises(KeyError):
        apply_overrides(cfg, {"rx.nonexistent": 1})


@pytest.mark.parametrize("bad", [
    lambda: LinkConfig(data_rate_gtps=0.0),
    lambda: ClockingConfig(correlation=1.5),
    lambda: ClockingConfig(scheme="independent"),
    lambda: ClockingConfig(track_bw_hz=-1.0),
    lambda: LaneConfig(count=4, failed=(4,)),
    lambda: LaneConfig(count=4, repair="spare"),
    lambda: LaneConfig(count=2, skew_ps=(1.0, 2.0, 3.0)),
    lambda: ChannelConfig(kind="touchstone"),
    lambda: SimConfig(jitter_block=1000),
])
def test_invalid_values_fail_at_construction(bad):
    with pytest.raises(ValueError):
        bad()


def test_rlgc_preset_and_override():
    r0 = LinkConfig().rlgc()
    assert {k: r0[k] for k in PACKAGE_RLGC["standard"]} == PACKAGE_RLGC["standard"]
    cfg = LinkConfig(channel=ChannelConfig(loss_tangent=0.02))
    r = cfg.rlgc()
    assert r["loss_tangent"] == 0.02 and r["r_skin"] == PACKAGE_RLGC["standard"]["r_skin"]
    adv = apply_overrides(LinkConfig(), {"package.kind": "advanced"}).rlgc()
    assert {k: adv[k] for k in PACKAGE_RLGC["advanced"]} == PACKAGE_RLGC["advanced"]


def test_rlgc_l_and_c_come_from_the_stackup():
    """One geometry drives everything: Z0 = sqrt(L/C) is the preset, c^2 L C is
    the Hammerstad eps_eff of the stack-up (the same number the coupled-line
    crosstalk estimate uses), and an explicit L or C still wins."""
    import math
    from d2d_link.config.schema import C0, eps_eff_microstrip

    for kind in ("standard", "advanced"):
        cfg = apply_overrides(LinkConfig(), {"package.kind": kind})
        r, st = cfg.rlgc(), cfg.stackup()
        assert math.sqrt(r["l_h_m"] / r["c_f_m"]) == pytest.approx(r["z0_ohm"]) == pytest.approx(50.0)
        assert C0 ** 2 * r["l_h_m"] * r["c_f_m"] == pytest.approx(st["eps_eff"]) == pytest.approx(r["eps_eff"])
        assert st["eps_eff"] == pytest.approx(eps_eff_microstrip(st["eps_r"], st["trace_width_um"], st["dielectric_height_um"]))
        assert 1.0 < st["eps_eff"] < st["eps_r"]
    assert LinkConfig().stackup()["eps_eff"] == pytest.approx(2.537, abs=0.001)
    assert apply_overrides(LinkConfig(), {"package.kind": "advanced"}).stackup()["eps_eff"] == pytest.approx(2.38, abs=0.001)
    z = LinkConfig(channel=ChannelConfig(z0_ohm=60.0)).rlgc()
    assert math.sqrt(z["l_h_m"] / z["c_f_m"]) == pytest.approx(60.0)
    e = LinkConfig(channel=ChannelConfig(l_h_m=4e-7)).rlgc()
    assert e["l_h_m"] == 4e-7 and e["c_f_m"] == pytest.approx(LinkConfig().rlgc()["c_f_m"])
    tall = LinkConfig(channel=ChannelConfig(eps_r=4.0)).rlgc()
    assert tall["c_f_m"] > LinkConfig().rlgc()["c_f_m"]                 # more dielectric: slower line


def test_tx_bandwidth_default_and_ideal():
    import math
    import numpy as np
    from d2d_link.channel.model import tx_response
    from d2d_link.config import TxConfig

    cfg = LinkConfig()
    assert cfg.tx.bw_hz is None and cfg.tx_bw_hz == pytest.approx(2.0 * cfg.f_nyquist)
    f = np.array([0.0, cfg.tx_bw_hz])
    assert abs(tx_response(cfg, f)[1]) == pytest.approx(1 / math.sqrt(2.0))
    ideal = LinkConfig(tx=TxConfig(bw_hz=math.inf))
    assert ideal.tx_bw_hz == math.inf and np.all(tx_response(ideal, f) == 1.0)
    with pytest.raises(ValueError):
        TxConfig(bw_hz=0.0)


def test_form_declares_every_field_and_nothing_else():
    assert set(FIELDS) == set(schema_paths())
    for path, fld in FIELDS.items():
        assert fld["label"] and fld["kind"], path


def test_form_values_roundtrip():
    cfg = load_config(REPO / "configs" / "standard_32g_x16_repair.yaml")
    values = config_to_values(cfg)
    assert values["clocking.track_bw_hz"] == pytest.approx(2.0)      # MHz on the form
    assert values["clocking.data_path_rj_s"] == pytest.approx(200.0)  # fs on the form
    back = apply_overrides(LinkConfig(), values_to_overrides(values))
    assert back == cfg


def test_schema_version_in_dump(tmp_path):
    out = tmp_path / "d.yaml"
    dump_config(LinkConfig(), out)
    assert yaml.safe_load(out.read_text())["schema_version"] == 1
