"""Invariant #5: every specification number carries its source; unverified ones are grep-able."""

import re

import pytest

from conftest import REPO
from d2d_link import spec
from d2d_link.config import LinkConfig
from d2d_link.engine.statistical import resolved_targets


def test_every_entry_is_tagged_and_cited():
    table = spec.all_entries()
    assert len(table) >= 10
    for key, e in table.items():
        assert e.source in spec.SOURCES, key
        assert e.cite, key
        if e.source == "survey":
            assert "未核实" in e.note or e.note, key


def test_grep_lists_every_unverified_number():
    text = spec.SURVEY_FILE.read_text(encoding="utf-8")
    n_grep = len(re.findall(r"^\s*source: survey\s*$", text, flags=re.M))
    assert n_grep == len(spec.unverified())


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
