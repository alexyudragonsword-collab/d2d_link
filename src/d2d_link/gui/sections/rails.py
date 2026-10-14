"""The right rail: this page's provenance, the queue, exports, the
unverified inputs the verdict leans on. And the left rail's scenario list."""

from __future__ import annotations

from pathlib import Path

from dash import dcc, html

from ...spec import all_entries, survey
from ..figures import bathtub_figure
from .common import chip


def this_page(state, result: dict | None, job) -> html.Div:
    rows = []
    if result:
        rep = result["report"]
        n_model = sum(1 for k in ("rdc_ohm_m", "r_skin", "loss_tangent", "z0_ohm") if k in rep["channel_model"])
        n_survey = sum(1 for v in rep["targets"].values() if v["source"] == "survey")
        rows = [("rendered from", f"run · {result['elapsed_s']:.1f} s"),
                ("engine", f"statistical · BER {rep['targets']['ber']['value']:.0e}"),
                ("overrides vs YAML", str(len(state.overrides)) if state.overrides else "none"),
                ("sources leaned on", html.Span([chip("model"), f" {n_model} ", chip("survey"), f" {n_survey}"]))]
    elif job is not None and job.status in ("queued", "running"):
        rows = [("status", job.status), ("overrides vs YAML", str(len(state.overrides)) or "none")]
    else:
        rows = [("status", "not run")]
    return html.Div([html.H4(["This page", html.Span("results match the file" if not state.overrides else
                                                      f"{len(state.overrides)} override(s)", className="aside")])]
                    + [html.Div([html.Span(k, className="k"), html.Span(v, className="v")], className="kv") for k, v in rows],
                    className="card")


def queue(jobs: list, manager) -> html.Div:
    items = []
    for j in reversed(jobs[-8:]):
        icon = {"queued": "◌", "running": "⟳", "done": "✔", "failed": "✘", "cancelled": "–"}[j.status]
        sub = j.scope
        if j.status == "running":
            eta = manager.eta_s(j)
            if j.progress and j.progress[1] > 1:
                sub += f" · {j.progress[0]} / {j.progress[1]} runs"
            sub += f" · {j.elapsed_s:.0f} s" + (f" · ~{eta:.0f} s left" if eta is not None else "")
        elif j.status == "done" and j.result:
            sub += f" · {j.result.get('elapsed_s', 0):.1f} s"
            if j.kind == "run":
                sub += " · " + ("PASS" if j.result.get("passes") else "FAIL")
            elif j.kind == "sensitivity":
                n = sum(1 for r in j.result["sensitivity"]["rows"] if r["flips"])
                sub += f" · {n} flip(s)"
            elif j.kind == "rate_sweep":
                sub += " · " + "/".join("✔" if r["passes"] else "✘" for r in j.result["rows"])
        elif j.status == "failed":
            sub += f" · {j.error}"
        items.append(html.Div([html.Span(icon, className=f"q-icon {j.status}"),
                               html.Div([html.Div(f"{j.label} · {j.kind}" if j.kind != "run" else j.label, className="q-lbl"),
                                         html.Div(sub, className="q-sub")]),
                               html.Button("✕", id={"type": "cancel", "id": j.id}, className="q-cancel",
                                           title="cancel") if j.status in ("queued", "running") else None],
                              className="q-item"))
    if not items:
        items = [html.Div("nothing queued", className="q-sub")]
    n_run = sum(1 for j in jobs if j.status == "running")
    return html.Div([html.H4(["Queue", html.Span(f"{manager.workers or 'inline'} worker(s) · {n_run} running",
                                                 className="aside")])] + items, className="card")


def exports(result: dict | None) -> html.Div:
    dis = result is None
    return html.Div([
        html.H4("Export this page"),
        html.Div([html.Button("Markdown", id="btn-export-md", disabled=dis, className="btn"),
                  html.Button("JSON", id="btn-export-json", disabled=dis, className="btn"),
                  html.Button("Overrides YAML", id="btn-export-yaml", className="btn")], className="btn-row"),
        html.P("The Markdown is the text of tools/budget_report.py; the page adds nothing the report doesn't say.",
               className="fine"),
    ], className="card")


def unverified(result: dict | None) -> html.Div:
    if not result:
        return html.Div([html.H4("Unverified inputs")], className="card")
    entries = all_entries()
    rows = []
    keys = {"eye_width_ui": "eye width ≥", "eye_height_mv": "eye height ≥", "ber": "raw BER"}
    for k, label in keys.items():
        t = result["report"]["targets"][k]
        if t["source"] != "survey":
            continue
        cite = ""
        for e in entries.values():
            if e.key.endswith(k) or k in e.key:
                cite = e.cite
                break
        rows.append(html.Div([html.Span(f"{label} {t['value']:g}", className="k"),
                              html.Span(cite if len(cite) <= 90 else cite[:88] + "…", className="v")], className="uv-item"))
    x = result["report"]["crosstalk"]
    if x.get("mode") == "coupled" and x.get("pitch_source") == "survey":
        rows.append(html.Div([html.Span(f"bump pitch {x['pitch_um']:g} µm", className="k"),
                              html.Span("survey table", className="v")], className="uv-item"))
    return html.Div([html.H4(["Unverified inputs", chip("survey")]), *rows,
                     html.P("When the spec text is in, these become spec and the page re-runs.", className="fine")],
                    className="card")


def scenarios(configs_dir: Path, current: Path | None, manager) -> html.Div:
    items = []
    for p in sorted(configs_dir.glob("*.yaml")):
        job = None
        for j in reversed(manager.poll()):
            if j.label == p.stem and j.kind == "run" and j.status == "done":
                job = j
                break
        sub = "not run yet"
        dot = "pending"
        if job and job.result:
            r = job.result
            w = min(r["lanes"], key=lambda q: q["margin"])
            sub = f"{'PASS' if r['passes'] else 'FAIL'} · {1e3 * w['eye_height_v']:.1f} mV / {w['eye_width_ui']:.3f} UI · {r['elapsed_s']:.1f} s"
            dot = "pass" if r["passes"] else "fail"
        items.append(html.Div([html.Span("●", className=f"dot {dot}"),
                               html.Div([html.Div(p.stem, className="sc-name"), html.Div(sub, className="sc-sub")])],
                              className="sc-item" + (" on" if current and p.resolve() == current.resolve() else ""),
                              id={"type": "scenario", "path": str(p)}))
    return html.Div([html.H4(["Scenarios", html.Span("configs/", className="aside")]), *items], className="card")




def inspector(result: dict | None, selected: int | None) -> html.Div:
    """The selected lane: eye against the targets, its bathtub, what it sees."""
    if not result:
        return html.Div([html.H4("Inspector"), html.P("run the link, then click a lane", className="fine")], className="card")
    lanes = result["lanes"]
    r = next((q for q in lanes if q["lane"] == selected), None)
    if r is None:
        r = next(q for q in lanes if q["lane"] == result["worst_lane"])
    t = result["report"]["targets"]
    ew_t, eh_t = t["eye_width_ui"]["value"], t["eye_height_mv"]["value"]

    def bullet(label, frac, tick, text, ok):
        return html.Div([html.Span(label, className="ins-lbl"),
                         html.Div([html.Div(className="ins-fill " + ("ok" if ok else "fail"), style={"width": f"{100 * min(frac, 1):.1f}%"}),
                                   html.Div(className="ins-tick", style={"left": f"{100 * min(tick, 1):.1f}%"})], className="ins-trk"),
                         html.Span(text, className="ins-val")], className="ins-row")

    amp = max(2.0 * r["main_cursor_v"], 1e-9)
    rows = [
        bullet("eye height", r["eye_height_v"] / amp, 1e-3 * eh_t / amp, f"{1e3 * r['eye_height_v']:.1f} mV ({r['eye_height_margin_mv']:+.1f})",
               r["eye_height_margin_mv"] >= 0),
        bullet("eye width", r["eye_width_ui"], ew_t, f"{r['eye_width_ui']:.3f} UI ({r['eye_width_margin_ui']:+.3f})",
               r["eye_width_margin_ui"] >= 0),
    ]
    facts = [("BER at the sampling phase", f"10^{r['log10_ber']:.1f}"), ("sampling phase", f"{r['phase_ui']:+.4f} UI"),
             ("jitter at the sampler", f"{1e15 * r['sigma_jitter_s']:.1f} fs"), ("noise at the sampler", f"{1e3 * r['sigma_noise_v']:.2f} mV"),
             ("ISI cursors", str(r["n_cursors"])), ("aggressors", f"{r['n_aggressors']} · {1e3 * r['xtalk_rms_v']:.2f} mV RMS"),
             ("skew residual", f"{r['skew_residual_ui']:+.4f} UI")]
    if r.get("centre_offset_ui"):
        facts.append(("training offset", f"{r['centre_offset_ui']:+.4f} UI"))
    fig = bathtub_figure([r], t["ber"]["value"], r["lane"], height=190)
    fig.update_layout(margin=dict(l=40, r=8, t=8, b=32), showlegend=False)
    fig.update_xaxes(title_text=None)
    fig.update_yaxes(title_text=None)
    return html.Div([html.H4(["Inspector", html.Span(f"lane {r['lane']} · physical {r['physical']}"
                                                      + (" · worst" if r["lane"] == result["worst_lane"] else ""), className="aside")]),
                     *rows, dcc.Graph(figure=fig, config={"displayModeBar": False, "staticPlot": True}, style={"height": "190px"}),
                     *[html.Div([html.Span(k, className="k"), html.Span(v, className="v")], className="kv") for k, v in facts]],
                    className="card")


def rates(result: dict | None, cfg, job, manager) -> html.Div:
    """C -- data rate x package: this config at every survey rate (a job)."""
    rate_list = [float(x) for x in survey("data_rates_gtps").value]
    t = result["report"]["targets"] if result else None
    head = html.H4(["Data rate × package", html.Span(f"{cfg.package.kind} · {cfg.channel.length_mm:g} mm", className="aside")])
    if result is None:
        return html.Div([head, html.P("run the link first", className="fine")], className="card")
    if job is None or job.status in ("failed", "cancelled"):
        return html.Div([head, html.P(f"this config at {', '.join(f'{r:g}' for r in rate_list)} GT/s: {len(rate_list)} runs", className="fine"),
                         html.Button("Run rate sweep", id={"type": "action", "name": "rate_sweep"}, n_clicks=0, className="btn"),
                         html.P(f"last attempt failed: {job.error}", className="fine") if job is not None and job.error else None],
                        className="card")
    if job.status in ("queued", "running"):
        done, total = job.progress or (0, len(rate_list))
        return html.Div([head, html.Div(html.Div(className="pbar-fill", style={"width": f"{100.0 * done / max(total, 1):.0f}%"}), className="pbar"),
                         html.P(f"{done} / {total} rates", className="fine")], className="card")
    rows = job.result["rows"]
    cells = [html.Div(f"{r['rate_gtps']:g}", className="rt-h") for r in rows]
    vals = [html.Div([html.Div(f"{r['eye_height_mv']:.0f}", className="rt-mv"), html.Div(f"{r['eye_width_ui']:.3f}", className="rt-ui")],
                     className="rt-cell " + ("ok" if r["passes"] else "fail"), title=f"worst lane {r['worst_lane']} · IL {r['il_db']:.2f} dB")
            for r in rows]
    first_fail = next((r for r in rows if not r["passes"]), None)
    note = (f"first failing rate {first_fail['rate_gtps']:g} GT/s (eye {first_fail['eye_height_mv']:.1f} mV / {first_fail['eye_width_ui']:.3f} UI "
            f"vs {t['eye_height_mv']['value']:g} mV / {t['eye_width_ui']['value']:g} UI)" if first_fail else "every rate passes")
    return html.Div([head, html.Div(cells + vals, className="rt-grid", style={"gridTemplateColumns": f"repeat({len(rows)}, 1fr)"}),
                     html.P(f"min eye height [mV] over lanes / min eye width [UI] at {t['ber']['value']:.0e}; {note}.", className="fine")],
                    className="card")


__all__ = ["this_page", "queue", "exports", "unverified", "scenarios", "inspector", "rates"]
