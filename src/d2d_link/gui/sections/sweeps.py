"""Appendix A-C -- sweeps: the config along one axis (tracker bandwidth,
local PLL natural frequency, line length), each a job of one run per point.
Until a sweep has run its block offers it with the point count."""

from __future__ import annotations

from dash import dcc, html

from ..figures import sweep_figure
from ..jobs import SWEEP_AXES
from .common import section

TITLES = {"track_bw": ("A", "Tracker bandwidth", "the per-lane phase tracker's bandwidth; none = no tracker"),
          "local_pll_fn": ("B", "Local PLL natural frequency", "the receiver's local PLL, locked to the forwarded clock"),
          "reach": ("C", "Reach", "line length at this rate and package; the survey reach is the config's own length")}


def _table(rows: list[dict], label: str) -> html.Table:
    head = html.Tr([html.Th(h) for h in (label, "residual [fs]", "min eye H [mV]", "min eye W [UI]", "worst lane", "pass")])
    body = [html.Tr([html.Td("none" if r["value"] is None else f"{r['value']:g}"), html.Td(f"{r['residual_fs']:.1f}"),
                     html.Td(f"{r['eye_height_mv']:.1f}"), html.Td(f"{r['eye_width_ui']:.3f}"), html.Td(str(r["worst_lane"])),
                     html.Td("✔ yes" if r["passes"] else "✘ no", className="ok" if r["passes"] else "fail")]) for r in rows]
    return html.Table([html.Thead(head), html.Tbody(body)], className="lanes")


def sweep_block(axis: str, result: dict, job, cfg) -> html.Div:
    letter, title, blurb = TITLES[axis]
    path, label, points = SWEEP_AXES[axis]
    head = html.Div([html.Span(letter, className="num"), html.H3(title),
                     html.Span(blurb, className="aside")], className="sec-head sub")
    if axis == "local_pll_fn" and not cfg.clocking.has_local_pll:
        return html.Div([head, html.P("this config has no local PLL (clocking.local_pll_profile / local_pll_rj_s): nothing to sweep.",
                                      className="fine")], className="sweep")
    if job is None or job.status in ("failed", "cancelled"):
        body = [html.P([f"{len(points)} points along {label}, one run each. ",
                        html.Button(f"Run sweep {letter}", id={"type": "action", "name": f"sweep:{axis}"}, n_clicks=0, className="btn")],
                       className="note")]
        if job is not None and job.error:
            body.append(html.P(f"last attempt failed: {job.error}", className="fine"))
        return html.Div([head, *body], className="sweep")
    if job.status in ("queued", "running"):
        done, total = job.progress or (0, len(points))
        return html.Div([head, html.Div(html.Div(className="pbar-fill", style={"width": f"{100.0 * done / max(total, 1):.0f}%"}), className="pbar"),
                         html.P(f"{done} / {total} points", className="fine")], className="sweep")
    rows = job.result["rows"]
    t = result["report"]["targets"]
    passing = [r for r in rows if r["passes"]]
    if axis == "reach":
        last = max((r["value"] for r in passing), default=None)
        summary = (f"last passing length {last:g} mm" if last is not None else "no length passes") + \
                  f"; the config's own {cfg.channel.length_mm:g} mm {'passes' if any(r['passes'] and r['value'] == cfg.channel.length_mm for r in rows) else 'is not on the grid or fails'}."
    elif axis == "track_bw":
        first = next((r for r in rows if r["value"] is not None and r["residual_fs"] <= 0.5 * rows[0]["residual_fs"]), None)
        summary = (f"the residual halves at {first['value']:.0e} Hz" if first else "no bandwidth on the grid halves the residual") + \
                  f"; eye width {rows[0]['eye_width_ui']:.3f} → {rows[-1]['eye_width_ui']:.3f} UI from no tracker to {rows[-1]['value']:.0e} Hz."
    else:
        best = max(rows, key=lambda r: r["eye_width_ui"])
        summary = f"widest eye {best['eye_width_ui']:.3f} UI at f_n {best['value']:.0e} Hz; residual {min(r['residual_fs'] for r in rows):.1f}–{max(r['residual_fs'] for r in rows):.1f} fs."
    return html.Div([head, html.P(summary, className="note"),
                     dcc.Graph(figure=sweep_figure(rows, label, t, log_x=axis != "reach"), config={"displayModeBar": False}),
                     _table(rows, label)], className="sweep")


def sweeps(result: dict, jobs_by_axis: dict, cfg) -> html.Section:
    blocks = [sweep_block(axis, result, jobs_by_axis.get(axis), cfg) for axis in ("track_bw", "local_pll_fn", "reach")]
    return section("sweeps", "A–C", "Sweeps", "one run per point · each a queued job", *blocks)


__all__ = ["sweeps", "sweep_block"]
