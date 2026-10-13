"""The right rail: this page's provenance, the queue, exports, the
unverified inputs the verdict leans on. And the left rail's scenario list."""

from __future__ import annotations

from pathlib import Path

from dash import html

from ...spec import all_entries
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
            sub += f" · {j.elapsed_s:.0f} s" + (f" · ~{eta:.0f} s left" if eta is not None else "")
        elif j.status == "done" and j.result:
            sub += f" · {j.result.get('elapsed_s', 0):.1f} s · " + ("PASS" if j.result.get("passes") else "FAIL")
        elif j.status == "failed":
            sub += f" · {j.error}"
        items.append(html.Div([html.Span(icon, className=f"q-icon {j.status}"),
                               html.Div([html.Div(j.label, className="q-lbl"), html.Div(sub, className="q-sub")]),
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
            if j.label == p.stem and j.status == "done":
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


__all__ = ["this_page", "queue", "exports", "unverified", "scenarios"]
