"""The Dash app: layout, the one refresh callback, the drawer and exports.

    d2d-link-gui configs/standard_32g_x16_module.yaml [--port 8050] [--workers 2]

Single-user by design: one ``PageState`` and one ``JobManager`` live in the
server process; the browser polls every second. Every edit on the page is an
override on the frozen config; every number on the page is read from a job
result (invariant #1).
"""

from __future__ import annotations

import argparse
import atexit
from pathlib import Path

from dash import ALL, Dash, Input, Output, ctx, dcc, html, no_update

from ..config.form import FIELDS, values_to_overrides
from . import export
from .drawer import drawer, drawer_head
from .jobs import JobManager, config_hash, default_cache_dir
from .sections import rails
from .sections.common import section
from .sections.compare import compare
from .sections.eyes import eyes
from .sections.flips import flips
from .sections.header import headline, lede
from .sections.jitter import jitter
from .sections.lanes import lanes
from .sections.sweeps import sweeps
from .sections.verdict import verdict
from .state import PageState

SECTION_TOC = [("verdict", "1", "Verdict"), ("flips", "2", "What flips the verdict"), ("jitter", "3", "Clock-path jitter"),
               ("eyes", "4", "Eye & bathtub per lane"), ("lanes", "5", "Lanes & repair"),
               ("crosstalk", "6", "Crosstalk"), ("receiver", "7", "Receiver"), ("sweeps", "A–C", "Sweeps")]


class App:
    """What the callbacks close over."""

    def __init__(self, configs_dir: Path, workers: int = 2, cache_dir: Path | None = None):
        self.configs_dir = configs_dir
        self.state = PageState()
        self.manager = JobManager(workers=workers, cache_dir=cache_dir)
        self.open_groups: set[str] = set()
        self.drawer_open = False
        self.shown: dict | None = None          # the last result rendered (kept while a re-run is pending)
        self.edit_error: str | None = None      # why the last edit was rejected, until the next edit
        self._scenario_hashes: dict[str, tuple[float, str]] = {}   # path -> (mtime, config hash)
        self._keys: tuple = (None, None, None, None)                # what the last render was made of

    # --------------------------------------------------------------- runs
    def label(self) -> str:
        label = self.state.config_path.stem if self.state.config_path else "config"
        if self.state.overrides:
            label += f" +{len(self.state.overrides)}"
        return label

    def run(self, kind: str = "run") -> None:
        """Queue a job on the current config; ``sweep:<axis>`` picks a sweep."""
        cfg = self.state.cfg
        params = None
        if kind.startswith("sweep:"):
            kind, axis = "sweep", kind.split(":", 1)[1]
            params = {"axis": axis}
        job = self.manager.submit(kind, cfg, params=params, label=self.label(), scope=f"{cfg.lanes.count} lanes")
        if kind == "run":
            self.state.job_id = job.id          # the This page card follows it (it read "not run" while running)

    def sweep_jobs(self) -> dict:
        """axis -> latest done or pending sweep job for the current config."""
        h = config_hash(self.state.cfg)
        out = {}
        for j in reversed(self.manager.poll()):
            if j.kind == "sweep" and j.cfg_hash == h and j.status in ("done", "queued", "running"):
                out.setdefault(j.params.get("axis"), j)
        return out

    def compare_result(self):
        """(result, job) of the scenario chosen in 'Compare with', queueing its run once."""
        path = self.state.compare_path
        if path is None:
            return None, None
        from ..config import load_config

        try:
            cfg = load_config(path)
        except Exception:                       # noqa: BLE001 -- handle() refuses such a file; one edited since is dropped here
            self.state.compare_path = None
            return None, None
        h = config_hash(cfg)
        done = self.manager.latest_done(h)
        if done is not None:
            return done.result, done
        job = self.manager.pending(h)
        if job is None:
            job = self.manager.submit("run", cfg, label=path.stem, scope=f"{cfg.lanes.count} lanes")
        return (job.result, job) if job.status == "done" else (None, job)

    def job_for(self, kind: str):
        """The latest done job of ``kind`` for the current config, else the pending one, else None."""
        h = config_hash(self.state.cfg)
        return self.manager.latest_done(h, kind) or self.manager.pending(h, kind)

    def sensitivity_runs(self) -> int:
        from ..report import sensitivity_knobs

        return 1 + 2 * len(sensitivity_knobs(self.state.cfg))

    def current_result(self) -> tuple[dict | None, bool]:
        """(result to show, stale): the run of the current config if done,
        else the last shown one flagged stale -- whether a run is pending or
        the config was edited without one (it used to read as current then)."""
        h = config_hash(self.state.cfg)
        self.manager.poll()
        done = self.manager.latest_done(h)
        if done is not None:
            sens = self.manager.latest_done(h, "sensitivity")
            if sens is not None:
                done.result["sensitivity"] = sens.result["sensitivity"]
            self.shown = done.result
            return done.result, False
        return self.shown, self.shown is not None

    def current_failure(self):
        """The failed run of the current config when nothing newer succeeded
        or is pending: the page says so instead of showing an older result."""
        return self.manager.latest_failed(config_hash(self.state.cfg))

    def scenario_hashes(self) -> dict[str, str]:
        """path -> config hash of every scenario file (re-read when its mtime
        changes), so the scenario list finds the file's own run and not a
        run with overrides on top of it."""
        from ..config import load_config

        out = {}
        for p in sorted(self.configs_dir.glob("*.yaml")):
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            cached = self._scenario_hashes.get(str(p))
            if cached is None or cached[0] != mtime:
                try:
                    cached = (mtime, config_hash(load_config(p)))
                except Exception:        # noqa: BLE001 -- a file that does not load has no run to show
                    cached = (mtime, "")
                self._scenario_hashes[str(p)] = cached
            if cached[1]:
                out[str(p)] = cached[1]
        return out

    # ------------------------------------------------------------- render
    def page(self) -> html.Div:
        cfg = self.state.cfg
        result, stale = self.current_result()
        failed = self.current_failure()
        kids = [html.Div("Timing budget · statistical engine" + (f" · run in {result['elapsed_s']:.1f} s" if result else ""),
                         className="kicker"), headline(cfg, result), lede(cfg, result)]
        if failed is not None:
            kids.append(html.Div([html.B("This configuration's run failed: "), html.Span(failed.error or "no detail"),
                                  html.Span("  The numbers below are the last successful run's." if result else "")],
                                 className="banner fail", role="alert"))
        if result:
            rep = result["report"]
            sel = self.state.selected_lane
            sens_job = self.job_for("sensitivity")
            est = None
            if sens_job is None:
                run_job = self.manager.latest_done(config_hash(cfg))
                est = (run_job.result["elapsed_s"] * self.sensitivity_runs()) if run_job and run_job.result else None
            kids.append(verdict(result))
            if self.state.compare_path is not None:
                other, other_job = self.compare_result()
                kids.append(compare(result, other, self.label(), self.state.compare_path.stem, other_job))
            kids += [flips(result, sens_job, self.sensitivity_runs(), est), jitter(result),
                     eyes(result, sel), lanes(result, sel),
                     section("crosstalk", "6", "Crosstalk", rep["crosstalk"]["mode"], html.P(_crosstalk_text(rep), className="note")),
                     section("receiver", "7", "Receiver", None, html.P(_receiver_text(rep), className="note")),
                     sweeps(result, self.sweep_jobs(), cfg)]
        elif failed is None:
            kids.append(html.P("Pick a scenario on the left or press Run.", className="note"))
        return html.Div(kids, className="page" + (" stale" if stale or (failed is not None and result) else ""))

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
                elif anchor == "flips":
                    sj = self.job_for("sensitivity")
                    aside = ("not run" if sj is None else "running" if sj.status in ("queued", "running") else
                             f"{sum(1 for r in sj.result['sensitivity']['rows'] if r['flips'])} / {len(sj.result['sensitivity']['rows'])}"
                             if sj.status == "done" else sj.status)
                elif anchor == "eyes":
                    aside = str(len(result["lanes"]))
            toc.append(html.A([f"{num} {title}", html.Span(aside, className="aside")], href=f"#sec-{anchor}"))
        return [rails.scenarios(self.configs_dir, self.state.config_path, self.manager, self.scenario_hashes()),
                rails.compare_picker(self.configs_dir, self.state.config_path, self.state.compare_path),
                html.Div([html.H4("On this page")] + toc, className="card toc")]

    def right(self) -> list:
        result, _ = self.current_result()
        jobs = self.manager.poll()
        job = self.manager.get(self.state.job_id) if self.state.job_id else None
        return [rails.this_page(self.state, result, job, self.current_failure(), self.edit_error), rails.queue(jobs, self.manager),
                rails.inspector(result, self.state.selected_lane),
                rails.rates(result, self.state.cfg, self.job_for("rate_sweep"), self.manager),
                rails.exports(result), rails.unverified(result)]

    def drawer(self) -> html.Div:
        return drawer(self.state, self.open_groups, self.edit_error)

    # ------------------------------------------------------------- edits
    def apply_edit(self, path: str, raw) -> bool:
        """An input's new value as an override; True when the config changed.
        A value the form cannot convert or the schema rejects is dropped and
        the reason kept in ``edit_error`` (shown in the drawer and the This
        page card) until the next edit; the page never raises on an edit."""
        fld = FIELDS[path]
        before = config_hash(self.state.cfg)
        had = path in self.state.overrides
        old = self.state.overrides.get(path)
        had_osr, old_osr = "sim.osr" in self.state.overrides, self.state.overrides.get("sim.osr")
        try:
            value = bool(raw) if fld["kind"] == "bool" else values_to_overrides({path: raw})[path]
            if path == "data_rate_gtps":
                # the waveform grid's top frequency (osr x f_N) stays where the
                # file put it: the rate edit carries the osr with_data_rate
                # gives from the file's own rate and osr -- validated before
                # anything is set, and the same osr whatever rates were tried
                # before (it read 42 after 32 -> 12 -> 24 and 43 directly)
                from ..config import apply_overrides, with_data_rate

                st = self.state
                rest = {k: v for k, v in st.overrides.items() if k not in ("data_rate_gtps", "sim.osr")}
                base = apply_overrides(st.file_cfg, rest) if st.file_cfg is not None else st.cfg
                moved = with_data_rate(base, value)
                st.set("sim.osr", moved.sim.osr)
            self.state.set(path, value)
            after = config_hash(self.state.cfg)       # builds the frozen config: validation happens here
        except Exception as exc:                      # noqa: BLE001 -- an invalid edit is dropped, the page stays
            if had:
                self.state.overrides[path] = old
            else:
                self.state.overrides.pop(path, None)
            if path == "data_rate_gtps":
                if had_osr:
                    self.state.overrides["sim.osr"] = old_osr
                else:
                    self.state.overrides.pop("sim.osr", None)
            self.edit_error = f"{fld['label']}: {exc}"
            return False
        self.edit_error = None
        return after != before

    # ----------------------------------------------------------- handlers
    def render_keys(self) -> tuple:
        """(page/left key, right key, drawer key, label): what each output is
        made of. A tick that changes none of them re-renders nothing -- the
        browser keeps its figures (hover, zoom) and the server does no work."""
        st = self.state
        jobs = self.manager.poll()
        statuses = tuple((j.id, j.status, j.progress) for j in jobs)
        running = tuple((j.id, int(j.elapsed_s or 0)) for j in jobs if j.status == "running")
        base = (str(st.config_path), tuple(sorted(st.overrides.items(), key=lambda kv: kv[0])), st.selected_lane,
                str(st.compare_path), statuses, self.edit_error)
        page_key = base
        right_key = (base, running)
        drawer_key = (str(st.config_path), tuple(sorted(st.overrides.items(), key=lambda kv: kv[0])),
                      tuple(sorted(self.open_groups)), self.edit_error)
        label = (str(st.config_path) if st.config_path else "no config") + (
            f"  · {len(st.overrides)} override(s)" if st.overrides else "")
        return page_key, right_key, drawer_key, label

    def handle(self, trig, inputs_list: list, force: bool = False) -> tuple:
        """The refresh callback's body: apply what ``trig`` asks, then render
        what changed. ``inputs_list`` is Dash's ``ctx.inputs_list`` (position
        = the Input's position in the callback). Returns the five outputs,
        ``no_update`` where nothing moved."""
        st = self.state
        if isinstance(trig, dict):
            kind = trig["type"]
            if kind == "scenario" and _clicked(inputs_list, trig, 1):
                try:
                    st.open(Path(trig["path"]))
                except Exception as exc:          # noqa: BLE001 -- a broken file is said, the page stays
                    self.edit_error = f"{Path(trig['path']).name} does not load: {exc}"
                else:
                    self.shown = None
                    self.edit_error = None
                    self.run()
            elif kind in ("headline", "field"):
                raw = _value_of(inputs_list, trig)
                if raw is not None and self.apply_edit(trig["path"], raw) and kind == "headline":
                    self.run()
            elif kind == "group" and _clicked(inputs_list, trig, 4):
                self.open_groups ^= {trig["key"]}
            elif kind == "cancel" and _clicked(inputs_list, trig, 5):
                self.manager.cancel(trig["id"])
            elif kind in ("lane-cell", "lane-row") and _clicked(inputs_list, trig, 9 if kind == "lane-cell" else 10):
                st.selected_lane = None if st.selected_lane == trig["lane"] else trig["lane"]
            elif kind == "action" and _clicked(inputs_list, trig, 11):
                self.run(trig["name"])
            elif kind == "compare":
                value = next((i.get("value") for i in inputs_list[12] if i["id"] == trig), None)
                st.compare_path = None
                if value:
                    from ..config import load_config

                    try:
                        load_config(value)
                        st.compare_path = Path(value)
                    except Exception as exc:      # noqa: BLE001 -- every later render raised on a broken file
                        self.edit_error = f"{Path(value).name} does not load: {exc}"
        elif trig in ("btn-rerun", "btn-rerun-drawer"):
            self.run()
        elif trig == "btn-discard":
            st.overrides.clear()
            self.edit_error = None

        page_key, right_key, drawer_key, label = self.render_keys()
        last_page, last_right, last_drawer, last_label = self._keys
        self._keys = (page_key, right_key, drawer_key, label)
        full = force or trig != "tick"
        page = left = right = drawer_out = label_out = no_update
        if full or page_key != last_page:
            page, left = self.page(), self.left()
        if full or right_key != last_right:
            right = self.right()
        if full or drawer_key != last_drawer:
            drawer_out = self.drawer()
        if full or label != last_label:
            label_out = label
        return page, left, right, drawer_out, label_out

    def download(self, name: str):
        """The export buttons: ``(content, filename)`` or None when there is
        nothing to export yet."""
        result, _ = self.current_result()
        stem = self.state.config_path.stem if self.state.config_path else "link"
        if name == "yaml":
            return export.overrides_yaml(self.state.config_path, self.state.overrides), f"{stem}.overrides.yaml"
        if result is None:
            return None
        if name == "md":
            return export.markdown(result), f"{stem}.budget.md"
        return export.report_json(result), f"{stem}.budget.json"


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
               autorun: bool = True, drawer_open: bool = False, extra_jobs: tuple[str, ...] = (),
               cache_dir: str | Path | None = None) -> Dash:
    """The Dash app bound to a scenario directory; ``config`` opens one and
    (with ``autorun``) queues its run. ``cache_dir`` keeps results across
    sessions (None: memory only). The ``App`` object is ``dash_app.d2d``."""
    configs_dir = Path(configs_dir)
    core = App(configs_dir, workers=workers, cache_dir=Path(cache_dir) if cache_dir else None)
    core.drawer_open = drawer_open
    if config is not None:
        core.state.open(Path(config))
        if autorun:
            core.run()
            for kind in extra_jobs:
                core.run(kind)
    app = Dash(__name__, title="d2d_link budget", update_title=None, suppress_callback_exceptions=True)
    app.d2d = core
    atexit.register(core.manager.shutdown)      # the worker processes and the manager go with the server

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
        dcc.Interval(id="wake", interval=5000),      # pauses the tick while the tab is hidden (see below)
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
                  Input({"type": "lane-cell", "lane": ALL}, "n_clicks"), Input({"type": "lane-row", "lane": ALL}, "n_clicks"),
                  Input({"type": "action", "name": ALL}, "n_clicks"), Input({"type": "compare", "name": ALL}, "value"),
                  prevent_initial_call=False)
    def refresh(_tick, _sc, _hl, _fl, _gr, _cx, _r1, _r2, _dis, _lc, _lr, _ac, _cw):
        # a string id that is not in the layout is a client-side error in
        # Dash (the page renders nothing), so the buttons that come and go
        # with the result use pattern ids. The body lives on App.handle so
        # the tests drive it without a browser; a tick that changes nothing
        # returns no_update everywhere (phase 10: the page used to be
        # rebuilt every second, figures and all).
        return core.handle(ctx.triggered_id, ctx.inputs_list, force=ctx.triggered_id is None)

    @app.callback(Output("drawer-wrap", "className"), Input("btn-drawer-open", "n_clicks"),
                  Input("btn-drawer-close", "n_clicks"), prevent_initial_call=True)
    def toggle_drawer(_o, _c):
        core.drawer_open = ctx.triggered_id == "btn-drawer-open"
        return "drawer-wrap open" if core.drawer_open else "drawer-wrap"

    @app.callback(Output("download", "data"), Input({"type": "export", "name": ALL}, "n_clicks"),
                  prevent_initial_call=True)
    def downloads(_clicks):
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or not _clicked(ctx.inputs_list, trig, 0):
            return no_update                      # the buttons were re-rendered, nobody pressed one
        out = core.download(trig["name"])
        if out is None:
            return no_update
        return dcc.send_string(*out)

    # the tick stops while the tab is hidden and resumes within one wake
    # interval of coming back: a page nobody looks at should not run the server
    app.clientside_callback("function(n) { return document.hidden === true; }",
                            Output("tick", "disabled"), Input("wake", "n_intervals"))

    return app


def _clicked(inputs_list: list, trig_id, position: int) -> bool:
    """True when the pattern input at ``position`` fired with a real click
    (n_clicks set), not because the component was just (re)created."""
    for item in inputs_list[position]:
        if item["id"] == trig_id:
            return bool(item.get("value"))
    return False


def _value_of(inputs_list: list, trig_id: dict):
    for group in (2, 3):
        for item in inputs_list[group]:
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
    ap.add_argument("--also", default="",
                    help="comma-separated extra jobs to queue at start: sensitivity, rate_sweep, "
                         "sweep:track_bw, sweep:local_pll_fn, sweep:reach")
    ap.add_argument("--cache", type=Path, default=default_cache_dir(), help="result cache directory (survives restarts)")
    ap.add_argument("--no-cache", action="store_true", help="keep results in memory only")
    ap.add_argument("--compare", type=Path, help="start with this scenario in 'Compare with'")
    args = ap.parse_args(argv)
    configs_dir = args.configs or (args.config.parent if args.config else Path("configs"))
    from .jobs import SWEEP_AXES

    allowed = {"sensitivity", "rate_sweep"} | {f"sweep:{a}" for a in SWEEP_AXES}
    for k in (k for k in args.also.split(",") if k):
        if k not in allowed:
            ap.error(f"--also {k!r}: not a job; choose from {', '.join(sorted(allowed))}")
    app = create_app(configs_dir, args.config, workers=args.workers, autorun=not args.no_autorun,
                     drawer_open=args.open_drawer, extra_jobs=tuple(k for k in args.also.split(",") if k),
                     cache_dir=None if args.no_cache else args.cache)
    if args.compare:
        app.d2d.state.compare_path = args.compare
    print(f"d2d_link GUI on http://{args.host}:{args.port}  (scenarios: {configs_dir}; "
          f"cache: {'off' if args.no_cache else args.cache})")
    try:
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    finally:
        app.d2d.manager.shutdown()
    return 0


__all__ = ["create_app", "main", "App"]


if __name__ == "__main__":
    raise SystemExit(main())
