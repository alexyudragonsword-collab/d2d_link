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
    assert LinkConfig().rlgc() == PACKAGE_RLGC["standard"]
    cfg = LinkConfig(channel=ChannelConfig(loss_tangent=0.02))
    r = cfg.rlgc()
    assert r["loss_tangent"] == 0.02 and r["r_skin"] == PACKAGE_RLGC["standard"]["r_skin"]
    adv = apply_overrides(LinkConfig(), {"package.kind": "advanced"}).rlgc()
    assert adv == PACKAGE_RLGC["advanced"]


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
