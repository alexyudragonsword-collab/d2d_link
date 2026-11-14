"""Invariant #5: every specification number carries its source; unverified ones are grep-able."""

import re

import pytest

from conftest import REPO
from d2d_link import spec
from d2d_link.config import LinkConfig
from d2d_link.engine.statistical import resolved_targets


def test_every_entry_is_tagged_and_cited():
    table = spec.all_entries()
    assert len(table) == 16 + 12                     # + <package>.raw_ber_target@<rate> from ucie.raw_ber_by_rate (0.17.0)
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
    assert len(presets) == 30 and all(e.estimated and e.cite and e.note for e in presets.values())
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
    from d2d_link.config import LinkConfig
    from d2d_link.config.schema import PACKAGE_XTALK_SECOND_OFFSET_DB
    assert PACKAGE_XTALK_SECOND_OFFSET_DB["advanced"] == spec.preset("xtalk_second_offset_db", "advanced").value == -12.0
    adj, sec = LinkConfig().xtalk_db()
    assert sec == adj + PACKAGE_XTALK_SECOND_OFFSET_DB["standard"]     # the third health check's B9: no bare -12 left
    assert "l_h_m" not in PACKAGE_RLGC["standard"] and "c_f_m" not in PACKAGE_RLGC["standard"]


def test_grep_lists_every_unverified_number():
    """The command the docs promise -- ``grep -c "source: survey"`` on the
    table -- must count exactly the unverified entries: no header comment
    may contain the tag, and no entry may hide it elsewhere."""
    import subprocess

    out = subprocess.run(["grep", "-c", "source: survey", str(spec.SURVEY_FILE)], capture_output=True, text=True)
    assert int(out.stdout.strip()) == len(spec.unverified()) == 1          # standard.lane_repair (0.16.1, issue #2)


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
    assert t["ber"] == (1e-15, "spec") and t["eye_height_mv"][1] == "spec"          # 32 GT/s standard: 1e-15 (0.17.0)
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
    assert spec.survey("tx_swing_vpp").tag() == "0.4 V (source: spec)"
    assert spec.survey("standard.lane_repair").tag().endswith("(source: survey)")


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
    assert spec.SURVEY_FILE.is_relative_to(PACKAGE_DIR / "vendor" / "spec_sources" / "data")     # spec_sources, vendored (0.16.0)
    assert spec.PRESETS_FILE.is_relative_to(PACKAGE_DIR / "data")
    monkeypatch.chdir(tmp_path)                       # no data/ in the working directory
    p = resolve_data_file("data/clock_profiles/bench_markulic16_sspll_40m_10p24g.yaml")
    assert p.is_file() and p.is_relative_to(PACKAGE_DIR)
    assert resolve_data_file(str(tmp_path / "x.yaml")) == tmp_path / "x.yaml"
    # tomllib is 3.11+; the declaration is one line of text
    pyproject = (PACKAGE_DIR.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^d2d_link = \[.*"data/clock_profiles/\*\.yaml".*\]', pyproject, re.M), "package-data declaration"
    for glob in ("vendor/spec_sources/data/*.yaml", "vendor/spec_sources/legacy_keys/*.yaml"):
        assert re.search(r'^d2d_link = \[.*"' + re.escape(glob) + r'".*\]', pyproject, re.M), glob


def test_targets_resolve_through_rate_and_package_tiers(monkeypatch):
    """The lookup is tiered so a mask's numbers land per tier:
    ``<package>.<key>@<rate>`` first, the plain key last (0.13.5). Since
    0.14.0 24 and 32 GT/s take the 0.65 UI tier a 2025 analysis quotes
    (``rx_eye_width_ui@24-32``, a range since 0.14.5; source: spec since 0.16.1); every
    other rate takes the plain 0.75 UI, and the report names the key."""
    import dataclasses

    from d2d_link.config import LinkConfig
    from d2d_link.engine.statistical import resolved_targets, target_keys

    assert spec.tier_keys("rx_eye_width_ui", "standard", 32.0) == [
        "standard.rx_eye_width_ui@32", "standard.rx_eye_width_ui", "rx_eye_width_ui@32", "rx_eye_width_ui"]
    cfg = LinkConfig()
    assert target_keys(cfg) == {"ber": "standard.raw_ber_target@32", "eye_height_mv": "rx_eye_height_mv",
                                "eye_width_ui": "rx_eye_width_ui@24-32"}          # the 24-32 GT/s range (0.14.5)
    table = dict(spec.all_entries())
    base = table["rx_eye_width_ui"]
    table["rx_eye_width_ui@32"] = dataclasses.replace(base, key="rx_eye_width_ui@32", value=0.70)
    table["standard.rx_eye_width_ui@32"] = dataclasses.replace(base, key="standard.rx_eye_width_ui@32", value=0.65)
    monkeypatch.setattr(spec, "_table", lambda: table)
    import d2d_link.engine.statistical as st
    monkeypatch.setattr(st, "survey_tiered", lambda *a, **k: spec.survey_tiered(*a, **k, table=table))
    assert resolved_targets(cfg)["eye_width_ui"] == (0.65, "spec")
    assert target_keys(cfg)["eye_width_ui"] == "standard.rx_eye_width_ui@32"
    adv = dataclasses.replace(cfg, package=dataclasses.replace(cfg.package, kind="advanced"))
    assert resolved_targets(adv)["eye_width_ui"][0] == 0.70                      # rate tier, no package tier
    table["advanced.rx_eye_width_ui"] = dataclasses.replace(base, key="advanced.rx_eye_width_ui", value=0.60)
    assert resolved_targets(adv)["eye_width_ui"][0] == 0.60                      # the package outranks the rate tier
    del table["advanced.rx_eye_width_ui"]
    slow = dataclasses.replace(cfg, data_rate_gtps=16.0)
    assert resolved_targets(slow)["eye_width_ui"][0] == 0.75 and target_keys(slow)["eye_width_ui"] == "rx_eye_width_ui"


def test_bundled_config_jitters_are_the_model_presets():
    """The clock-path jitters every bundled config sets (data / clock path
    white, tree, path wander and its corner) decide the module verdicts
    (example 12: jitter is 51-100 % of every eye-width gap) and no public
    source gives them: since 0.13.11 they are ``source: model`` presets
    with what is known in their cite, and the configs must say the same
    number (a config that changes one is making its own claim -- then this
    test says so)."""
    from conftest import REPO
    from d2d_link.config import load_config

    keys = {"data_path_rj_s": "data_path_rj_s", "clock_path_rj_s": "clock_path_rj_s", "tree_rj_s": "tree_rj_s",
            "data_path_wander_s": "path_wander_s", "clock_path_wander_s": "path_wander_s",
            "wander_corner_hz": "wander_corner_hz"}
    for path in sorted((REPO / "configs").glob("*.yaml")):
        cfg = load_config(path)
        for field, key in keys.items():
            v = getattr(cfg.clocking, field)
            if v:
                assert v == spec.preset(key, cfg.package.kind).value, (path.name, field)


def test_the_eye_width_tier_is_a_rate_range():
    """The 0.65 UI quote is for "24 to 32 GT/s": one range entry answers
    every rate in it, the end points and 28 GT/s alike (0.14.0-0.14.4 had
    exact @24 / @32 entries and 28 GT/s fell back to 0.75 UI -- fifth health
    check). An exact rate entry still outranks a range at the same tier; a
    rate neither in the survey's list nor in a range falls back to the plain
    entry with a warning; overlapping ranges are refused."""
    import dataclasses
    import warnings

    from d2d_link.config import LinkConfig, with_data_rate
    from d2d_link.engine import statistical as st

    cfg = LinkConfig()
    for rate, want, key in ((24, 0.65, "rx_eye_width_ui@24-32"), (28, 0.65, "rx_eye_width_ui@24-32"),
                            (32, 0.65, "rx_eye_width_ui@24-32"), (16, 0.75, "rx_eye_width_ui")):
        c = with_data_rate(cfg, rate)
        assert st.resolved_targets(c)["eye_width_ui"] == (want, "spec"), rate
        assert st.target_keys(c)["eye_width_ui"] == key, rate
    st._OFF_TABLE_WARNED.clear()
    with pytest.warns(UserWarning, match="neither in the survey's rate list"):
        assert st.resolved_targets(with_data_rate(cfg, 40))["eye_width_ui"][0] == 0.75
    st._OFF_TABLE_WARNED.clear()
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        st.resolved_targets(with_data_rate(cfg, 28))                    # inside the range: no eye-width warning
    assert not any("eye-width" in str(w.message) for w in rec)          # (the raw BER warns there since 0.17.1)
    table = dict(spec.all_entries())
    base = table["rx_eye_width_ui@24-32"]
    table["rx_eye_width_ui@28"] = dataclasses.replace(base, key="rx_eye_width_ui@28", value=0.60)
    assert spec.survey_tiered("rx_eye_width_ui", "standard", 28.0, table=table).value == 0.60     # exact beats range
    table["rx_eye_width_ui@30-40"] = dataclasses.replace(base, key="rx_eye_width_ui@30-40", value=0.55)
    with pytest.raises(ValueError, match="overlapping"):
        spec.survey_tiered("rx_eye_width_ui", "standard", 31.0, table=table)


def test_tier_fallback_and_overlap_are_caught(tmp_path, monkeypatch):
    """Sixth health check leftovers (0.15.6): a rate in no tier (20 GT/s)
    falls back with a warning and the report flags it; overlapping ranges
    are refused when the table is read, not only when a rate in the overlap
    is asked for."""
    from d2d_link.config import LinkConfig, with_data_rate
    from d2d_link.engine import statistical as st
    from d2d_link.report import build

    st._OFF_TABLE_WARNED.clear()
    c20 = with_data_rate(LinkConfig(), 20)
    with pytest.warns(UserWarning, match="neither in the survey's rate list"):
        assert st.resolved_targets(c20)["eye_width_ui"][0] == 0.75
    assert st.off_table_rate(c20) and not st.off_table_rate(with_data_rate(LinkConfig(), 28))
    assert build(LinkConfig())["targets"]["eye_width_ui"]["off_table"] is False
    bad = tmp_path / "t.yaml"
    entry = 'value: 0.6\n    unit: UI\n    source: survey\n    cite: "x"\n    note: "未核实"'
    bad.write_text(f"entries:\n  w@10-20:\n    {entry}\n  w@15-30:\n    {entry}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="overlapping rate ranges"):
        spec.load_survey(bad)


def test_shim_keys_are_the_old_keys():
    """0.16.0: the UCIe numbers are spec_sources' ``ucie.*`` entries, vendored
    and pinned; the shim hangs them on this library's old bare keys in the
    old table's order, value for value, and the vendored table passes
    spec_sources' own tag guard (each of its four tags' grep count equals its
    entries) -- issue #1."""
    from d2d_link.vendor.spec_sources import reader as ss

    legacy = ss.legacy_keys("d2d_link")
    assert list(spec.all_entries())[:len(legacy)] == list(legacy)             # then the BER tiers (0.17.0)
    shared = ss.load_table(spec.SURVEY_FILE)
    for old, new in legacy.items():
        e, s = spec.survey(old), shared[new]
        assert e.key == old and e.value == s.value and e.unit == s.unit and e.source == s.source and e.cite == s.cite
        assert e.quote == (s.quote or "") and e.section == (s.section or "")
    assert ss.audit_tags(spec.SURVEY_FILE) == []
    assert spec.survey_tiered("rx_eye_width_ui", "standard", 28.0).key == "rx_eye_width_ui@24-32"


def test_raw_ber_target_follows_the_rate_by_package_table():
    """Issue #2 point 2 (0.17.0): the raw BER target is the rate x package
    table spec_sources quotes -- 1e-15 from 12 GT/s on the standard package
    and from 16 GT/s on the advanced, 1e-27 below -- each tier a ``ref`` into
    ``ucie.raw_ber_by_rate``; a rate the table does not list falls back to
    the plain 1e-27 entry. Until 0.16.1 every rate used 1e-27."""
    from d2d_link.config import LinkConfig, PackageConfig, with_data_rate
    from d2d_link.engine import statistical as st
    from d2d_link.vendor.spec_sources import reader as ss

    shared = ss.load_table(spec.SURVEY_FILE)
    for kind, first_relaxed in (("standard", 12), ("advanced", 16)):
        cfg = LinkConfig(package=PackageConfig(kind=kind))
        for rate in (4, 8, 12, 16, 24, 32):
            c = with_data_rate(cfg, rate)
            want = ss.ref(f"ucie.raw_ber_by_rate#{kind}@data_rate_gtps={rate}", shared)
            assert want == (1e-15 if rate >= first_relaxed else 1e-27), (kind, rate)
            assert st.resolved_targets(c)["ber"] == (want, "spec"), (kind, rate)
            assert st.target_keys(c)["ber"] == f"{kind}.raw_ber_target@{rate}"
    st._OFF_TABLE_WARNED.clear()
    with pytest.warns(UserWarning, match="raw-BER tiers"):
        assert st.resolved_targets(with_data_rate(LinkConfig(), 20))["ber"] == (1e-27, "spec")    # no tier: the plain entry


def test_raw_ber_fallback_off_the_table_is_flagged():
    """spec_sources' review of issue #2: 28 GT/s sits inside the eye-width
    range tier (no warning there) but in no raw-BER tier, so its BER fell
    back to the plain 1e-27 silently although 24 and 32 GT/s both ask
    1e-15. Since 0.17.1 it warns once per rate and package and the report
    flags ``targets.ber.off_table``; a listed rate and a configured BER do
    not."""
    import warnings

    from d2d_link.clock.forwarded import ForwardedClock
    from d2d_link.config import LinkConfig, PackageConfig, SimConfig, TargetConfig, with_data_rate
    from d2d_link.engine import run_link
    from d2d_link.engine import statistical as st
    from d2d_link.report import report as build_report
    from d2d_link.report import to_markdown

    st._OFF_TABLE_WARNED.clear()
    for kind in ("standard", "advanced"):
        c28 = with_data_rate(LinkConfig(package=PackageConfig(kind=kind)), 28)
        assert st.off_table_ber(c28) and not st.off_table_rate(c28)
        with pytest.warns(UserWarning, match=f"28 GT/s is not in the {kind} package's raw-BER tiers") as rec:
            assert st.resolved_targets(c28)["ber"] == (1e-27, "spec")
        assert not any("eye-width" in str(w.message) for w in rec)              # the eye width is covered by @24-32
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            st.resolved_targets(c28)                                            # once per rate and package
    c32 = LinkConfig()
    assert not st.off_table_ber(c32)
    assert not st.off_table_ber(with_data_rate(LinkConfig(target=TargetConfig(ber=1e-27)), 28))   # the config's own claim
    assert st.off_table_targets(with_data_rate(LinkConfig(), 28)) == {"ber": True, "eye_height_mv": False, "eye_width_ui": False}

    c = with_data_rate(LinkConfig(sim=SimConfig(stat_phase_points=16)), 28)
    rep = build_report(c, run_link(c), ForwardedClock(c))
    assert rep["targets"]["ber"]["off_table"] is True and rep["targets"]["eye_width_ui"]["off_table"] is False
    assert "| ber | 1e-27 | spec | raw_ber_target (rate in no tier" in to_markdown(rep)
