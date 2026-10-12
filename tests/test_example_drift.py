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
