"""tools/example_drift.py: expected outputs cover every example and are stored
masked; a moved number is paired and found in the docs that quote it.
Adapted from Halo_Serdes tests/test_example_drift.py."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def drift():
    spec = importlib.util.spec_from_file_location("example_drift", REPO / "tools" / "example_drift.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


def test_expected_outputs_cover_every_example(drift):
    examples = {p.stem for p in (REPO / "examples").glob("[0-9][0-9]_*.py")}
    assert {p.stem for p in drift.EXPECTED.glob("*.txt")} == examples


def test_expected_outputs_are_stored_normalised(drift):
    for p in sorted(drift.EXPECTED.glob("*.txt")):
        text = p.read_text(encoding="utf-8")
        assert drift.normalise(text) == text, p.name


def test_timings_and_paths_are_masked(drift):
    raw = "a  [3.2s]\n18 runs in 33s\n  wrote /home/runner/work/d/d/examples/output/00_x.png\n"
    assert drift.normalise(raw) == "a  [~s]\n18 runs in ~s\n  wrote examples/output/00_x.png\n"


def test_number_tokens_and_rounding(drift):
    assert drift.NUM.findall("-22.7dB 1.1e-27 UCIe1.0 v1.5.2 (11) 180m") == ["-22.7", "1.1e-27", "11", "180"]
    assert drift.rounds_to("4.7", 4.66) and not drift.rounds_to("4.7", 4.76)


def test_changes_pair_numbers(drift):
    old = "head\n  eye 93.2 mV 0.829 UI\ntail\n"
    new = "head\n  eye 93.5 mV 0.829 UI\ntail\n"
    (ch,) = drift.changes("00_x", old, new)
    assert ch.pairs == [("93.2", "93.5")]


def test_stale_quotes_are_found_by_scope(drift, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "A.md").write_text("# One\n\n示例 00 的眼高 93.2 mV。\n\n# Two\n\n别处 93.2 mV。\n",
                                           encoding="utf-8")
    index = drift.DocIndex(drift.all_doc_numbers(tmp_path))
    ch = drift.Change("00_x", "", "", [("93.21", "93.50")])
    hits = sorted((d.lineno, where) for d, _, _, where in drift.stale(ch, index))
    assert hits == [(3, "block"), (7, "elsewhere")]


def test_every_registered_derived_quote_holds(drift):
    """The tool's docstring promised this and no test did it (third health
    check): every quote in examples/derived.yaml against the expected outputs."""
    entries = drift.load_derived()
    assert entries
    bad, broken = drift.check_derived(entries, drift._outputs(drift.EXPECTED), drift.REPO)
    assert not broken, broken
    assert not bad, [(e.name, doc, ln, tok, value) for e, doc, ln, tok, value in bad]


def test_accept_refuses_while_a_citing_table_quotes_a_moved_number(drift, tmp_path):
    """Phase 12 accepted example 07 with README's "194.7 mV" still quoting the
    old output; accept now refuses until the table is fixed (or --force)."""
    exp = tmp_path / "expected"
    new = tmp_path / "new"
    exp.mkdir()
    new.mkdir()
    doc = tmp_path / "README.md"
    doc.write_text("| `07_rate_sweep.py` | rate sweep | first failing rate 24 GT/s, eye 194.7 mV |\n", encoding="utf-8")
    (exp / "07_rate_sweep.txt").write_text("first failing rate 24 GT/s: eye 194.7 mV / 0.737 UI\n", encoding="utf-8")
    (new / "07_rate_sweep.txt").write_text("first failing rate 24 GT/s: eye 194.6 mV / 0.737 UI\n", encoding="utf-8")
    hits = drift.blocking_quotes(exp, new, tmp_path)
    assert [(h[0], h[2]) for h in hits] == [("README.md", "194.7")]
    doc.write_text("| `07_rate_sweep.py` | rate sweep | first failing rate 24 GT/s, eye 194.6 mV |\n", encoding="utf-8")
    assert drift.blocking_quotes(exp, new, tmp_path) == []


def test_accept_gate_reads_history_releases_and_spec_numbers_as_no_quote(drift, tmp_path):
    """Phase 15's accept flagged 104 doc numbers for 8 real stale quotes: a
    number labelled with an older release ("0.12 的 194.7"), a release number
    itself ("到 0.11 为止"), and a spec-table number an output passes by
    ("0.75 UI", the eye-width target) are not quotes of today's output. A
    since-then statement ("0.12 起 194.7") still is."""
    exp = tmp_path / "expected"
    new = tmp_path / "new"
    exp.mkdir()
    new.mkdir()
    (tmp_path / "pyproject.toml").write_text('version = "0.13.2"\n', encoding="utf-8")
    doc = tmp_path / "README.md"
    (exp / "07_rate_sweep.txt").write_text("first failing rate 24 GT/s: eye 194.7 mV / 0.747 UI\n", encoding="utf-8")
    (new / "07_rate_sweep.txt").write_text("first failing rate 24 GT/s: eye 194.6 mV / 0.691 UI\n", encoding="utf-8")
    doc.write_text("| `07_rate_sweep.py` | rate sweep | eye 194.6 mV against the 0.75 UI target"
                   "(0.12 的口径下 194.7 mV;到 0.11 为止 0.11 的数) |\n", encoding="utf-8")
    assert drift.blocking_quotes(exp, new, tmp_path) == []
    doc.write_text("| `07_rate_sweep.py` | rate sweep | 0.12 起 eye 194.7 mV |\n", encoding="utf-8")
    assert [h[2] for h in drift.blocking_quotes(exp, new, tmp_path)] == ["194.7"]
    doc.write_text("| `07_rate_sweep.py` | rate sweep | 0.13.0 的 eye 194.7 mV |\n", encoding="utf-8")
    assert [h[2] for h in drift.blocking_quotes(exp, new, tmp_path)] == ["194.7"]   # today's release is not history
    doc.write_text("| `07_rate_sweep.py` | rate sweep | eye 194.6 mV(0.13.2 前 194.7 mV) |\n", encoding="utf-8")
    assert drift.blocking_quotes(exp, new, tmp_path) == []                          # ... unless marked as the past
    spans, versions = drift.history_spans("0.11 UI 与 0.5 与 0.12.3 的 1.5 mV", 13)
    assert versions == {"0.11 UI 与 0.5 与 0.12.3 的 1.5 mV".index("0.12.3")} and len(spans) == 1
