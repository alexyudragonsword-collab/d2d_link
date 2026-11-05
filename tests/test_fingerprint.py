"""Invariant #6: the fingerprint tool catches a moved value; engines are deterministic."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from conftest import PROFILE
from d2d_link.config import ClockingConfig, LinkConfig, SimConfig
from d2d_link.engine import run_statistical, run_time

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def fp():
    spec = importlib.util.spec_from_file_location("fingerprint", REPO / "tools" / "fingerprint.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_compare_finds_every_kind_of_difference(fp):
    a = {"configs": {"c": {"stat/0": {"ber": "0.1", "bathtub": "abc"}}}, "synthetic": {"x": "1"}}
    assert fp.compare(a, json.loads(json.dumps(a))) == (3, [])
    b = {"configs": {"c": {"stat/0": {"ber": "0.1", "bathtub": "abd", "new": "1"}}}, "synthetic": {"x": "2"}}
    n, diffs = fp.compare(a, b)
    assert n == 4 and len(diffs) == 3 and diffs[0].startswith("configs / c / stat/0 / bathtub")


def test_compare_cli_exit_codes(fp, tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"k": "1"}))
    b.write_text(json.dumps({"k": "1"}))
    assert fp.main(["compare", str(a), str(b)]) == 0
    b.write_text(json.dumps({"k": "2"}))
    assert fp.main(["compare", str(a), str(b)]) == 1
    assert "k: '1' -> '2'" in capsys.readouterr().out


def test_raised_entries_are_listed(fp):
    side = {"configs": {"c": {"error": "TypeError: bad"}, "d": {"stat/0": {"ber": "0"}}}}
    assert fp.raised(side) == ["configs / c: TypeError: bad"]


def test_engines_are_deterministic(fp):
    cfg = LinkConfig(clocking=ClockingConfig(pll_profile=PROFILE, data_path_rj_s=300e-15),
                     sim=SimConfig(n_symbols=5_000, stat_phase_points=16))
    s1, s2 = run_statistical(cfg), run_statistical(cfg)
    assert fp.stat_values(s1) == fp.stat_values(s2)
    t1, t2 = run_time(cfg, phase_ui=0.0), run_time(cfg, phase_ui=0.0)
    assert fp.time_values(t1) == fp.time_values(t2)
    assert fp.digest(np.arange(3.0)) == fp.digest([0.0, 1.0, 2.0])


def test_fingerprint_walk_names_the_unmarked_commit_that_moved():
    """Fourth health check: one (numbers-move commit in a push waived the
    whole range. The walk settles a moved range commit by commit."""
    import importlib.util

    from conftest import REPO

    spec = importlib.util.spec_from_file_location("fingerprint_walk", REPO / "tools" / "fingerprint_walk.py")
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    fps = {"base": {"x": 1}, "a": {"x": 1}, "b": {"x": 2}, "c": {"x": 3}}
    rec = lambda sha, out: fps[sha]                                       # noqa: E731
    ok, _ = w.settle("base", fps["base"], fps["base"], [], 12, rec, ["a"], lambda s: False)
    assert ok                                                             # nothing moved
    ok, _ = w.settle("base", fps["base"], fps["c"], [], 12, rec, ["a", "b", "c"], lambda s: False)
    assert not ok                                                         # moved, nothing marked
    ok, _ = w.settle("base", fps["base"], fps["c"], [], 12, rec, ["a", "b", "c"], lambda s: True)
    assert ok                                                             # every commit marked
    ok, msgs = w.settle("base", fps["base"], fps["c"], [], 12, rec, ["a", "b", "c"], lambda s: s == "b")
    assert not ok and any("error: c" in m for m in msgs)                  # b says so, c does not
    ok, msgs = w.settle("base", fps["base"], fps["c"], [], 12, rec, ["a", "b", "c"], lambda s: s in ("b", "c"))
    assert ok and any(m.startswith("a unmarked: 0") for m in msgs)        # a moved nothing
    assert w.settle("base", fps["base"], fps["c"], ["numbers-move"], 12, rec, ["a"], lambda s: False)[0]
    assert w.MARKER.search("x (numbers-move: why)") and not w.MARKER.search("no numbers-move needed")
