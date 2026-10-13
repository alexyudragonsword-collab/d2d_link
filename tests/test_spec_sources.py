"""Invariant #5: every specification number carries its source; unverified ones are grep-able."""

import re

import pytest

from conftest import REPO
from d2d_link import spec
from d2d_link.config import LinkConfig
from d2d_link.engine.statistical import resolved_targets


def test_every_entry_is_tagged_and_cited():
    table = spec.all_entries()
    assert len(table) == 15
    for key, e in table.items():
        assert e.source in spec.SOURCES, key
        assert e.cite, key
        if e.source == "survey":
            assert "未核实" in e.note, f"{key}: a survey entry's note must say it is unverified"


def test_model_presets_are_tagged_and_grep_able():
    """The numbers the spec does not own (trace loss, stack-up, behavioural
    crosstalk) are estimates: every one carries ``source: model`` and the
    grep the docs promise counts exactly the entries. The survey table may
    not hold an estimate, nor the preset table a spec number."""
    import subprocess

    presets = spec.all_presets()
    assert len(presets) == 18 and all(e.estimated and e.cite and e.note for e in presets.values())
    out = subprocess.run(["grep", "-c", "source: model"], input=spec.PRESETS_FILE.read_text(encoding="utf-8"),
                         capture_output=True, text=True)
    assert int(out.stdout.strip()) == len(presets)
    assert not any(e.estimated for e in spec.all_entries().values())
    with pytest.raises(ValueError, match="does not belong"):
        spec.load_survey(spec.PRESETS_FILE)
    with pytest.raises(ValueError, match="does not belong"):
        spec.load_survey(spec.SURVEY_FILE, allowed=("model",))
    for pkg in ("standard", "advanced"):
        assert spec.preset("z0_ohm", pkg).value == 50.0
    with pytest.raises(KeyError):
        spec.preset("nonexistent", "standard")
    from d2d_link.config.schema import PACKAGE_RLGC, PACKAGE_STACKUP, PACKAGE_XTALK_DB
    assert PACKAGE_RLGC["standard"]["r_skin"] == spec.preset("r_skin", "standard").value
    assert PACKAGE_STACKUP["advanced"]["eps_r"] == spec.preset("eps_r", "advanced").value
    assert PACKAGE_XTALK_DB["standard"] == spec.preset("xtalk_adjacent_db", "standard").value
    assert "l_h_m" not in PACKAGE_RLGC["standard"] and "c_f_m" not in PACKAGE_RLGC["standard"]


def test_grep_lists_every_unverified_number():
    """The command the docs promise -- ``grep -c "source: survey"`` on the
    table -- must count exactly the unverified entries: no header comment
    may contain the tag, and no entry may hide it elsewhere."""
    import subprocess

    out = subprocess.run(["grep", "-c", "source: survey", str(spec.SURVEY_FILE)], capture_output=True, text=True)
    assert int(out.stdout.strip()) == len(spec.unverified()) == 15


def test_spec_source_needs_a_quote():
    with pytest.raises(ValueError, match="quoted"):
        spec.SpecNumber("x", 1, "u", "spec", "cite")
    with pytest.raises(ValueError, match="source"):
        spec.SpecNumber("x", 1, "u", "rumour", "cite")
    ok = spec.SpecNumber("x", 1, "u", "spec", "cite", quote="the text", section="3.1")
    assert ok.verified


def test_package_lookup():
    assert spec.survey("reach_mm", "standard").value == pytest.approx(25.0)
    assert spec.survey("reach_mm", "advanced").value == pytest.approx(2.0)
    assert spec.survey("raw_ber_target", "standard").value == pytest.approx(1e-27)
    with pytest.raises(KeyError):
        spec.survey("nonexistent")


def test_targets_resolve_with_their_source():
    t = resolved_targets(LinkConfig())
    assert t["ber"] == (1e-27, "survey") and t["eye_height_mv"][1] == "survey"
    from d2d_link.config import TargetConfig
    t2 = resolved_targets(LinkConfig(target=TargetConfig(eye_height_mv=50.0)))
    assert t2["eye_height_mv"] == (50.0, "config")


def test_code_does_not_hardcode_the_table():
    from test_invariants import code_only

    src = REPO / "src" / "d2d_link"
    hits = []
    for p in src.rglob("*.py"):
        if "vendor" in p.parts or p.parent.name == "spec":
            continue
        for m in re.finditer(r"1(?:\.0)?e-27|\b25\.0\b|\b0\.75\b", code_only(p.read_text(encoding="utf-8"))):
            hits.append((p.relative_to(REPO), m.group(0)))
    assert not hits, hits


def test_tag_format():
    assert spec.survey("tx_swing_vpp").tag().endswith("(source: survey)")


def test_bundled_configs_stay_inside_the_survey_envelope():
    """A config may repeat a survey number (the swing, a length at the reach,
    a module width) only as the table has it: the swing equals the table's,
    lengths do not exceed the package's reach, lane counts do not exceed the
    module width. The literal is then a copy of the table, not a second
    source."""
    from d2d_link.config import load_config

    for p in sorted((REPO / "configs").glob("*.yaml")):
        cfg = load_config(p)
        kind = cfg.package.kind
        assert cfg.tx.swing_vpp == pytest.approx(spec.survey("tx_swing_vpp").value), p.name
        assert cfg.channel.length_mm <= spec.survey("reach_mm", kind).value + 1e-9, p.name
        assert cfg.lanes.count <= spec.survey("module_width_lanes", kind).value, p.name
        assert cfg.data_rate_gtps in [float(r) for r in spec.survey("data_rates_gtps").value], p.name


def test_data_ships_inside_the_package(tmp_path, monkeypatch):
    """The tables and the bundled clock profiles are package data
    (``src/d2d_link/data``): an installed d2d_link finds them away from the
    checkout, and a config's ``data/clock_profiles/x.yaml`` still resolves."""
    from d2d_link.clock.forwarded import PACKAGE_DIR, resolve_data_file

    assert spec.SURVEY_FILE.is_file() and spec.PRESETS_FILE.is_file()
    assert spec.SURVEY_FILE.is_relative_to(PACKAGE_DIR / "data")
    monkeypatch.chdir(tmp_path)                       # no data/ in the working directory
    p = resolve_data_file("data/clock_profiles/bench_markulic16_sspll_40m_10p24g.yaml")
    assert p.is_file() and p.is_relative_to(PACKAGE_DIR)
    assert resolve_data_file(str(tmp_path / "x.yaml")) == tmp_path / "x.yaml"
    import tomllib

    pyproject = tomllib.loads((PACKAGE_DIR.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert "data/clock_profiles/*.yaml" in pyproject["tool"]["setuptools"]["package-data"]["d2d_link"]
