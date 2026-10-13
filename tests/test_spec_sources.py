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
