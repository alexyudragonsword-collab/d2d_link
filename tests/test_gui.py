"""Phase 8: the browser GUI holds no simulation logic (invariant #1), renders
the report's numbers verbatim, queues runs and caches them. No browser is
started: the sections are pure functions of a job result and the Dash app
is built and exercised through its ``App`` core."""

import ast
import json
from pathlib import Path

import pytest

pytest.importorskip("dash")

from d2d_link.config import load_config  # noqa: E402
from d2d_link.gui import export  # noqa: E402
from d2d_link.gui.app import create_app  # noqa: E402
from d2d_link.gui.jobs import JobManager, config_hash, execute  # noqa: E402
from d2d_link.gui.state import PageState, source_of  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GUI = REPO / "src" / "d2d_link" / "gui"
ALLOWED = {"d2d_link.config", "d2d_link.config.form", "d2d_link.config.loader", "d2d_link.config.schema",
           "d2d_link.engine", "d2d_link.engine.lanes", "d2d_link.report", "d2d_link.spec", "d2d_link.clock.forwarded",
           "d2d_link.channel.coupled"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    pkg = "d2d_link.gui" + ("." + path.parent.name if path.parent.name != "gui" else "")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                base = pkg.split(".")
                base = base[: len(base) - node.level + 1]
                out.add(".".join(base + [node.module]))
            else:
                out.add(node.module)
        elif isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
    return out


def test_gui_imports_only_the_public_surface():
    """Invariant #1: the GUI edits a LinkConfig, calls run_link and renders
    results. It never reaches into the engines, the channel or the clock
    beyond the closed-form budget and the crosstalk description."""
    for py in GUI.rglob("*.py"):
        for mod in _imports(py):
            if mod.startswith("d2d_link") and not mod.startswith("d2d_link.gui"):
                assert mod in ALLOWED, f"{py.relative_to(REPO)} imports {mod}"


@pytest.fixture(scope="module")
def x1_result():
    cfg = load_config(REPO / "configs" / "standard_32g_x1.yaml")
    from d2d_link.config.loader import config_to_dict

    return execute("run", config_to_dict(cfg))


def test_run_result_is_json_and_matches_the_example(x1_result):
    json.dumps(x1_result)                     # plain data across the process boundary
    lane = x1_result["lanes"][0]
    assert x1_result["passes"] and abs(1e3 * lane["eye_height_v"] - 215.6) < 0.1
    assert abs(lane["eye_width_ui"] - 0.774) < 0.001
    assert x1_result["report"]["jitter_budget"][-1]["term"].startswith("total")


def test_sections_render_the_report_numbers(x1_result):
    from d2d_link.gui.sections.header import headline
    from d2d_link.gui.sections.jitter import jitter
    from d2d_link.gui.sections.lanes import lanes
    from d2d_link.gui.sections.verdict import verdict

    cfg = load_config(REPO / "configs" / "standard_32g_x1.yaml")
    text = json.dumps([headline(cfg, x1_result).to_plotly_json(), verdict(x1_result).to_plotly_json(),
                       jitter(x1_result).to_plotly_json(), lanes(x1_result).to_plotly_json()], default=str)
    for needle in ("215.6", "0.774", "295.3", "survey", "PASS" if x1_result["passes"] else "FAIL", "Every lane passes"):
        assert needle in text


def test_export_markdown_is_the_cli_report(x1_result):
    from d2d_link.report import to_markdown

    assert export.markdown(x1_result) == to_markdown(x1_result["report"])
    assert json.loads(export.report_json(x1_result))["link"]["verdict"] == "PASS"
    assert "channel.length_mm: 30.0" in export.overrides_yaml("x.yaml", {"channel.length_mm": 30.0})


def test_state_overrides_and_sources():
    st = PageState()
    st.open(REPO / "configs" / "standard_32g_x1.yaml")
    assert source_of(st.cfg, "channel.length_mm", st.file_cfg) == "yaml"
    assert source_of(st.cfg, "channel.z0_ohm", st.file_cfg) == "model"
    assert source_of(st.cfg, "target.eye_width_ui", st.file_cfg) == "survey"
    st.set("channel.length_mm", 30.0)
    assert st.overrides == {"channel.length_mm": 30.0} and st.cfg.channel.length_mm == 30.0
    assert source_of(st.cfg, "channel.length_mm", st.file_cfg) == "override"
    st.set("channel.length_mm", 25.0)             # back to the file's value: the override goes
    assert st.overrides == {}
    rows = {r["path"]: r for r in st.rows()}
    assert rows["rx.noise_rms_v"]["value"] == 3.0 and rows["rx.noise_rms_v"]["source"] == "yaml"


def test_job_manager_inline_caches_by_config(x1_result):
    cfg = load_config(REPO / "configs" / "standard_32g_x1.yaml")
    m = JobManager(workers=0)
    a = m.submit("run", cfg, label="x1", scope="1 lanes")
    assert a.status == "done" and a.result["passes"]
    b = m.submit("run", cfg, label="x1 again", scope="1 lanes")
    assert b.status == "done" and b.result is a.result          # the cache, not a second run
    assert m.latest_done(config_hash(cfg)) is b
    with pytest.raises(ValueError):
        m.submit("nonsense", cfg)


def test_app_builds_and_edits_queue_runs(tmp_path):
    app = create_app(REPO / "configs", REPO / "configs" / "standard_32g_x1.yaml", workers=0)
    core = app.d2d
    result, stale = core.current_result()
    assert result is not None and not stale
    page = json.dumps(core.page().to_plotly_json(), default=str)
    assert "215.6" in page and "PASS" in page
    assert core.apply_edit("channel.length_mm", 30.0) and core.state.overrides == {"channel.length_mm": 30.0}
    assert not core.apply_edit("channel.length_mm", 30.0)          # unchanged: no new run
    assert not core.apply_edit("lanes.count", -4)                   # invalid: dropped, config intact
    assert "lanes.count" not in core.state.overrides
    core.run()
    r2, _ = core.current_result()
    assert r2["report"]["link"]["length_mm"] == 30.0
    core.open_groups = {"channel", "rx"}
    drawer_text = json.dumps(core.drawer().to_plotly_json(), default=str)
    assert "channel.length_mm" in drawer_text and "override" in drawer_text and "rx.noise_rms_v" in drawer_text
    for part in (core.left(), core.right(), core.drawer()):
        json.dumps([p.to_plotly_json() for p in (part if isinstance(part, list) else [part])], default=str)
    app.layout                                                      # the Dash layout builds


def test_every_bundled_config_opens_without_running():
    for p in sorted((REPO / "configs").glob("*.yaml")):
        app = create_app(REPO / "configs", p, workers=0, autorun=False)
        assert app.d2d.state.config_path == p
        json.dumps(app.d2d.page().to_plotly_json(), default=str)


# ----------------------------------------------------------------- G2
def _small():
    """A link the whole sensitivity sweep runs on in seconds."""
    from d2d_link.config import ChannelConfig, ClockingConfig, LinkConfig, RxConfig, SimConfig

    return LinkConfig(channel=ChannelConfig(length_mm=2.0), clocking=ClockingConfig(), rx=RxConfig(noise_rms_v=0.02),
                      sim=SimConfig(stat_phase_points=16))


def test_sensitivity_and_rate_sweep_jobs_inline():
    from d2d_link.report import sensitivity_knobs

    cfg = _small()
    m = JobManager(workers=0)
    s = m.submit("sensitivity", cfg, label="small", scope="1 lanes")
    assert s.status == "done", s.error
    rows = s.result["sensitivity"]["rows"]
    assert len(rows) == len(sensitivity_knobs(cfg)) + 2 and s.progress == (1 + 2 * len(sensitivity_knobs(cfg)),) * 2
    json.dumps(s.result)
    r = m.submit("rate_sweep", cfg, label="small", scope="1 lanes")
    assert r.status == "done", r.error
    assert [row["rate_gtps"] for row in r.result["rows"]] == [4.0, 8.0, 12.0, 16.0, 24.0, 32.0]
    assert r.progress == (6, 6)


def test_g2_sections_and_figures(x1_result):
    from d2d_link.gui.figures import bathtub_figure, tornado_figure
    from d2d_link.gui.sections.eyes import eyes
    from d2d_link.gui.sections.flips import flips
    from d2d_link.gui.sections.lanes import floor_plan, lanes
    from d2d_link.gui.sections.rails import inspector, rates

    fig = bathtub_figure(x1_result["lanes"], 1e-27, 0)
    assert len(fig.data) == 2            # the lane and its sampling marker
    text = json.dumps([eyes(x1_result, 0).to_plotly_json(), lanes(x1_result, 0).to_plotly_json(),
                       floor_plan(x1_result, 0).to_plotly_json(), inspector(x1_result, 0).to_plotly_json()], default=str)
    assert "fp-eye" in text and "0.774" in text and "Inspector" in text
    cfg = _small()
    m = JobManager(workers=0)
    s = m.submit("sensitivity", cfg)
    small = execute("run", __import__("d2d_link.config.loader", fromlist=["config_to_dict"]).config_to_dict(cfg))
    sec = json.dumps(flips(small, s, 9, None).to_plotly_json(), default=str)
    assert "flips this" in sec and "tornado" not in sec.lower() or "Bar" in sec
    assert len(tornado_figure(s.result["sensitivity"]).data) == 2
    assert "Run sensitivity" in json.dumps(flips(small, None, 9, 3.0).to_plotly_json(), default=str)
    r = m.submit("rate_sweep", cfg)
    card = json.dumps(rates(small, cfg, r, m).to_plotly_json(), default=str)
    assert "rt-cell" in card and ("every rate passes" in card or "first failing rate" in card)


def test_lane_selection_and_extra_jobs():
    app = create_app(REPO / "configs", REPO / "configs" / "standard_32g_x1.yaml", workers=0, autorun=False)
    core = app.d2d
    core.state.file_cfg = _small()
    core.run()
    core.run("rate_sweep")
    assert core.job_for("rate_sweep").status == "done" and core.job_for("sensitivity") is None
    core.state.selected_lane = 0
    page = json.dumps(core.page().to_plotly_json(), default=str)
    assert "fp-sel" in page and "lane 0 in front" in page
    right = json.dumps([c.to_plotly_json() for c in core.right()], default=str)
    assert "rt-grid" in right and "Inspector" in right
    core.run("sensitivity")
    assert core.job_for("sensitivity").status == "done"
    # every rail renders with sensitivity and sweep results beside the run (the scenario list once
    # picked the latest done job of any kind and read its lanes)
    json.dumps([c.to_plotly_json() for c in core.left()], default=str)
    page = json.dumps(core.page().to_plotly_json(), default=str)
    assert "flips this" in page
    assert "sensitivity" in export.markdown(core.current_result()[0]).lower()


def _text(component) -> str:
    """Every string in a component tree (``to_plotly_json`` reprs abbreviate deep children)."""
    out = []

    def walk(node):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, (list, tuple)):
            for n in node:
                walk(n)
        elif hasattr(node, "to_plotly_json"):
            props = node.to_plotly_json().get("props", {})
            for k, v in props.items():
                if k in ("children", "options", "title", "placeholder", "value", "id", "className"):
                    walk(v)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
    walk(component)
    return "\n".join(str(x) for x in out)


# ----------------------------------------------------------------- G3
def test_sweep_job_disk_cache_and_sections(tmp_path):
    from d2d_link.config.loader import config_to_dict
    from d2d_link.gui.figures import sweep_figure
    from d2d_link.gui.sections.compare import compare
    from d2d_link.gui.sections.sweeps import sweeps

    cfg = _small()
    m = JobManager(workers=0, cache_dir=tmp_path)
    j = m.submit("sweep", cfg, params={"axis": "reach", "points": [1.0, 2.0, 4.0]}, label="small", scope="1 lanes")
    assert j.status == "done", j.error
    rows = j.result["rows"]
    assert [r["value"] for r in rows] == [1.0, 2.0, 4.0] and all("residual_fs" in r for r in rows)
    assert j.progress == (3, 3)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert len(files) == 1 and files[0].startswith("sweep-")
    # a fresh manager on the same directory answers from disk, no run
    m2 = JobManager(workers=0, cache_dir=tmp_path)
    j2 = m2.submit("sweep", cfg, params={"axis": "reach", "points": [1.0, 2.0, 4.0]})
    assert j2.status == "done" and j2.result["rows"] == rows and j2.started == j2.finished
    small = execute("run", config_to_dict(cfg))
    assert len(sweep_figure(rows, "line length [mm]", small["report"]["targets"], log_x=False).data) == 2
    sec = _text(sweeps(small, {"reach": j}, cfg))
    assert ("last passing length" in sec or "no length passes" in sec) and "Run sweep A" in sec and "no local PLL" in sec
    cmp_sec = _text(compare(small, small, "a", "b", None))
    assert "worst-lane eye width" in cmp_sec and "cmp-row" in cmp_sec
    pending = _text(compare(small, None, "a", "b", None))
    assert "not run" in pending


def test_app_sweeps_and_compare(tmp_path):
    app = create_app(REPO / "configs", REPO / "configs" / "standard_32g_x1.yaml", workers=0, autorun=False, cache_dir=tmp_path)
    core = app.d2d
    core.state.file_cfg = _small()
    core.run()
    core.run("sweep:reach")
    assert core.sweep_jobs()["reach"].status == "done" and core.sweep_jobs()["reach"].params == {"axis": "reach"}
    core.state.compare_path = REPO / "configs" / "standard_32g_x1.yaml"
    other, job = core.compare_result()                  # queued and, inline, done at once
    assert other is not None and job.status == "done" and job.label == "standard_32g_x1"
    page = _text(core.page())
    assert "Compare with" in page and "worst-lane eye width" in page
    assert "last passing length" in page or "no length passes" in page
    left = _text(core.left())
    assert "compare" in left and "standard_32g_x16_repair" in left
    assert any(p.name.startswith("run-") for p in tmp_path.iterdir())
