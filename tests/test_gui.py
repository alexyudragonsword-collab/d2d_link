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
           "d2d_link.engine", "d2d_link.report", "d2d_link.spec", "d2d_link.clock.forwarded",
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
        m.submit("sweep", cfg)


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
