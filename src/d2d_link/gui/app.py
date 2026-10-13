"""The Dash app: layout, the one refresh callback, the drawer and exports.

    d2d-link-gui configs/standard_32g_x16_module.yaml [--port 8050] [--workers 2]

Single-user by design: one ``PageState`` and one ``JobManager`` live in the
server process; the browser polls every second. Every edit on the page is an
override on the frozen config; every number on the page is read from a job
result (invariant #1).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update

from ..config.form import FIELDS, values_to_overrides
from . import export
from .drawer import drawer, drawer_head
from .jobs import JobManager, config_hash
from .sections import rails
from .sections.common import section
from .sections.header import headline, lede
from .sections.jitter import jitter
from .sections.lanes import lanes
from .sections.verdict import verdict
from .state import PageState

SECTION_TOC = [("verdict", "1", "Verdict"), ("jitter", "3", "Clock-path jitter"), ("lanes", "5", "Lanes & repair"),
               ("crosstalk", "6", "Crosstalk"), ("receiver", "7", "Receiver")]


class App:
    """What the callbacks close over."""

    def __init__(self, configs_dir: Path, workers: int = 2):
        self.configs_dir = configs_dir
        self.state = PageState()
        self.manager = JobManager(workers=workers)
        self.open_groups: set[str] = set()
        self.drawer_open = False
        self.shown: dict | None = None          # the last result rendered (kept while a re-run is pending)

    # --------------------------------------------------------------- runs
    def run(self) -> None:
        cfg = self.state.cfg
        label = self.state.config_path.stem if self.state.config_path else "config"
        if self.state.overrides:
            label += f" +{len(self.state.overrides)}"
        self.manager.submit("run", cfg, label=label, scope=f"{cfg.lanes.count} lanes")

    def current_result(self) -> tuple[dict | None, bool]:
        """(result to show, stale): the run of the current config if done,
        else the last shown one flagged stale while a run is pending."""
        h = config_hash(self.state.cfg)
        jobs = self.manager.poll()
        done = self.manager.latest_done(h)
        if done is not None:
            self.shown = done.result
            return done.result, False
        pending = any(j.cfg_hash == h and j.status in ("queued", "running") for j in jobs)
        return self.shown, pending

    # ------------------------------------------------------------- render
    def page(self) -> html.Div:
        cfg = self.state.cfg
        result, stale = self.current_result()
        kids = [html.Div("Timing budget · statistical engine" + (f" · run in {result['elapsed_s']:.1f} s" if result else ""),
                         className="kicker"), headline(cfg, result), lede(cfg, result)]
        if result:
            rep = result["report"]
            kids += [verdict(result), jitter(result), lanes(result),
                     section("crosstalk", "6", "Crosstalk", rep["crosstalk"]["mode"], html.P(_crosstalk_text(rep), className="note")),
                     section("receiver", "7", "Receiver", None, html.P(_receiver_text(rep), className="note"))]
        else:
            kids.append(html.P("Pick a scenario on the left or press Run.", className="note"))
        return html.Div(kids, className="page" + (" stale" if stale else ""))

    def left(self) -> list:
        result, _ = self.current_result()
        toc = []
        for anchor, num, title in SECTION_TOC:
            aside = ""
            if result:
                if anchor == "verdict":
                    aside = "PASS" if result["passes"] else "FAIL"
                elif anchor == "jitter":
                    aside = f"{result['report']['jitter_budget'][-1]['fs']:.1f} fs"
                elif anchor == "lanes":
                    aside = f"{result['active']} / {result['requested']}"
            toc.append(html.A([f"{num} {title}", html.Span(aside, className="aside")], href=f"#sec-{anchor}"))
        return [rails.scenarios(self.configs_dir, self.state.config_path, self.manager),
                html.Div([html.H4("On this page")] + toc, className="card toc")]

    def right(self) -> list:
        result, _ = self.current_result()
        jobs = self.manager.poll()
        job = self.manager.get(self.state.job_id) if self.state.job_id else None
        return [rails.this_page(self.state, result, job), rails.queue(jobs, self.manager), rails.exports(result),
                rails.unverified(result)]

    def drawer(self) -> html.Div:
        return drawer(self.state, self.open_groups)

    # ------------------------------------------------------------- edits
    def apply_edit(self, path: str, raw) -> bool:
        """An input's new value as an override; True when the config changed."""
        fld = FIELDS[path]
        if fld["kind"] == "bool":
            value = bool(raw)
        else:
            value = values_to_overrides({path: raw})[path]
        before = config_hash(self.state.cfg)
        try:
            self.state.set(path, value)
            after = config_hash(self.state.cfg)       # builds the frozen config: validation happens here
        except Exception:                             # noqa: BLE001 -- an invalid edit is dropped, the page stays
            self.state.overrides.pop(path, None)
            return False
        return after != before


def _crosstalk_text(rep: dict) -> str:
    x = rep["crosstalk"]
    if x["mode"] == "coupled":
        return (f"Coupled-line estimate: pitch {x['pitch_um']:g} µm ({x['pitch_source']}), width {x['trace_width_um']:g} µm, "
                f"height {x['dielectric_height_um']:g} µm, ε_r {x['eps_r']:g} (ε_eff {x['eps_eff']:.2f}); FEXT at Nyquist "
                f"{x['fext_adjacent_db']:.1f} dB nearest, {x['fext_second_db']:.1f} dB second neighbour. A model estimate, "
                "not a specification value.")
    if x["mode"] == "fext":
        return f"Behavioural FEXT level {x['adjacent_db']:.1f} dB at Nyquist, nearest lane ({x['adjacent_source']})."
    if x["mode"] == "touchstone":
        return "Crosstalk from the Touchstone file's own coupling terms."
    return "Off."


def _receiver_text(rep: dict) -> str:
    rx = rep["receiver"]
    fe = "flat (an idealisation: no front-end pole)" if rx["bw_hz"] is None else f"{rx['bw_hz'] / 1e9:g} GHz first-order"
    where = (f"referred at the input in the Nyquist band, {rx['sigma_sampler_mv']:.2f} mV at the sampler "
             f"(front end × CTLE gain {rx['noise_gain']:.3f})" if rx["noise_at"] == "input"
             else "referred at the sampler (nothing shapes it)")
    ctle = f"CTLE {rx['ctle_peak_db']:g} dB peaking" if rx["ctle_peak_db"] is not None else "no CTLE"
    train = (f"training centres the eye at BER {rx['training_ber']:.0e}" if rx["training_ber"] is not None
             else "the sampler sits at the target opening's centre (ideal training)")
    return f"Front end {fe}; {ctle}; noise {rx['noise_rms_mv']:.2f} mV RMS {where}; {train}."


def create_app(configs_dir: str | Path = "configs", config: str | Path | None = None, workers: int = 2,
               autorun: bool = True, drawer_open: bool = False) -> Dash:
    """The Dash app bound to a scenario directory; ``config`` opens one and
    (with ``autorun``) queues its run. The ``App`` object is ``dash_app.d2d``."""
    configs_dir = Path(configs_dir)
    core = App(configs_dir, workers=workers)
    core.drawer_open = drawer_open
    if config is not None:
        core.state.open(Path(config))
        if autorun:
            core.run()
    app = Dash(__name__, title="d2d_link budget", update_title=None, suppress_callback_exceptions=True)
    app.d2d = core

    app.layout = html.Div([
        html.Div([html.Span(["d2d_link", html.Span("budget notebook")], className="brand"),
                  html.Span(id="topbar-cfg", className="cfg"),
                  html.Span(className="spacer"),
                  html.Button("All fields", id="btn-drawer-open", className="btn"),
                  html.Button("▶ Run", id="btn-rerun", className="btn primary")], className="topbar"),
        html.Div([html.Div(id="left", className="rail"), html.Div(id="page"), html.Div(id="right", className="rail")],
                 className="layout"),
        html.Div([drawer_head(), html.Div(id="drawer-inner", children=core.drawer())],
                 id="drawer-wrap", className="drawer-wrap open" if drawer_open else "drawer-wrap"),
        dcc.Interval(id="tick", interval=1000),
        dcc.Download(id="download"),
    ])

    @app.callback(Output("page", "children"), Output("left", "children"), Output("right", "children"),
                  Output("drawer-inner", "children"), Output("topbar-cfg", "children"),
                  Input("tick", "n_intervals"),
                  Input({"type": "scenario", "path": ALL}, "n_clicks"),
                  Input({"type": "headline", "path": ALL}, "value"),
                  Input({"type": "field", "path": ALL}, "value"),
                  Input({"type": "group", "key": ALL}, "n_clicks"),
                  Input({"type": "cancel", "id": ALL}, "n_clicks"),
                  Input("btn-rerun", "n_clicks"), Input("btn-rerun-drawer", "n_clicks"), Input("btn-discard", "n_clicks"),
                  prevent_initial_call=False)
    def refresh(_tick, _sc, _hl, _fl, _gr, _cx, _r1, _r2, _dis):
        trig = ctx.triggered_id
        st = core.state
        redraw_drawer = trig != "tick"          # the drawer re-renders only on an edit, a toggle or a new scenario
        if isinstance(trig, dict):
            kind = trig["type"]
            if kind == "scenario" and _clicked(ctx, 1):
                st.open(Path(trig["path"]))
                core.shown = None
                core.run()
            elif kind in ("headline", "field"):
                raw = _value_of(ctx, trig)
                if raw is not None and core.apply_edit(trig["path"], raw) and kind == "headline":
                    core.run()
            elif kind == "group" and _clicked(ctx, 4):
                core.open_groups ^= {trig["key"]}
            elif kind == "cancel" and _clicked(ctx, 5):
                core.manager.cancel(trig["id"])
        elif trig in ("btn-rerun", "btn-rerun-drawer"):
            core.run()
        elif trig == "btn-discard":
            st.overrides.clear()
        cfg_label = (str(st.config_path) if st.config_path else "no config") + (
            f"  · {len(st.overrides)} override(s)" if st.overrides else "")
        return core.page(), core.left(), core.right(), core.drawer() if redraw_drawer else no_update, cfg_label

    @app.callback(Output("drawer-wrap", "className"), Input("btn-drawer-open", "n_clicks"),
                  Input("btn-drawer-close", "n_clicks"), prevent_initial_call=True)
    def toggle_drawer(_o, _c):
        core.drawer_open = ctx.triggered_id == "btn-drawer-open"
        return "drawer-wrap open" if core.drawer_open else "drawer-wrap"

    @app.callback(Output("download", "data"), Input("btn-export-md", "n_clicks"), Input("btn-export-json", "n_clicks"),
                  Input("btn-export-yaml", "n_clicks"), State("topbar-cfg", "children"), prevent_initial_call=True)
    def downloads(_m, _j, _y, _label):
        result, _ = core.current_result()
        stem = core.state.config_path.stem if core.state.config_path else "link"
        if ctx.triggered_id == "btn-export-yaml":
            return dcc.send_string(export.overrides_yaml(core.state.config_path, core.state.overrides), f"{stem}.overrides.yaml")
        if result is None:
            return no_update
        if ctx.triggered_id == "btn-export-md":
            return dcc.send_string(export.markdown(result), f"{stem}.budget.md")
        return dcc.send_string(export.report_json(result), f"{stem}.budget.json")

    return app


def _clicked(c, position: int) -> bool:
    """True when the pattern input at ``position`` fired with a real click
    (n_clicks set), not because the component was just (re)created."""
    for item in c.inputs_list[position]:
        if item["id"] == c.triggered_id:
            return bool(item.get("value"))
    return False


def _value_of(c, trig_id: dict):
    for group in (2, 3):
        for item in c.inputs_list[group]:
            if item["id"] == trig_id:
                return item.get("value")
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="d2d_link browser GUI: the timing budget as a page")
    ap.add_argument("config", nargs="?", type=Path, help="a link config YAML to open and run")
    ap.add_argument("--configs", type=Path, help="scenario directory (default: the config's directory, or ./configs)")
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--workers", type=int, default=2, help="worker processes (0 = run inline)")
    ap.add_argument("--no-autorun", action="store_true")
    ap.add_argument("--open-drawer", action="store_true", help="start with the All-fields drawer open")
    args = ap.parse_args(argv)
    configs_dir = args.configs or (args.config.parent if args.config else Path("configs"))
    app = create_app(configs_dir, args.config, workers=args.workers, autorun=not args.no_autorun,
                     drawer_open=args.open_drawer)
    print(f"d2d_link GUI on http://{args.host}:{args.port}  (scenarios: {configs_dir})")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


__all__ = ["create_app", "main", "App"]


if __name__ == "__main__":
    raise SystemExit(main())
