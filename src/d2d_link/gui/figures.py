"""Plotly figures, each a pure function of job results. Light theme only."""

from __future__ import annotations

import math

import plotly.graph_objects as go

FONT = dict(family="Inter, Segoe UI, system-ui, sans-serif", size=12, color="#374151")
GRID = "#eef0f3"
BLUE, AMBER, GREEN, RED, DIM = "#2563eb", "#b45309", "#15803d", "#b91c1c", "#9ca3af"
FLOOR = -60.0        # log10 BER below this is drawn flat: the bathtub's depths are not physical


def _base(height: int, **kw) -> go.Layout:
    base = dict(height=height, margin=dict(l=52, r=16, t=22, b=40), paper_bgcolor="white", plot_bgcolor="white",
                font=FONT, legend=dict(orientation="h", y=1.08, x=0, font=dict(size=11)),
                xaxis=dict(gridcolor=GRID, zeroline=False), yaxis=dict(gridcolor=GRID, zeroline=False))
    base.update(kw)
    return go.Layout(**base)


def bathtub_figure(lanes: list[dict], target_ber: float, selected: int | None = None, height: int = 300) -> go.Figure:
    """log10 BER against sampling phase, one line per lane; the selected lane
    bold, the others faint; the target as a dashed line; sampling phases as
    markers. The floor is cosmetic (see FLOOR)."""
    fig = go.Figure(layout=_base(height))
    lt = math.log10(target_ber)
    for r in lanes:
        sel = selected is None or r["lane"] == selected
        y = [max(v, FLOOR) for v in r["bathtub_log10_ber"]]
        fig.add_trace(go.Scatter(x=r["bathtub_phase_ui"], y=y, mode="lines", name=f"lane {r['lane']}",
                                 line=dict(color=BLUE if sel else DIM, width=2.2 if sel else 1),
                                 opacity=1.0 if sel else 0.45, hovertemplate="%{x:+.3f} UI: 10^%{y:.0f}<extra>lane " + str(r["lane"]) + "</extra>"))
        if sel:
            fig.add_trace(go.Scatter(x=[r["phase_ui"]], y=[max(r["log10_ber"], FLOOR)], mode="markers", showlegend=False,
                                     marker=dict(color=GREEN, size=9, symbol="diamond"),
                                     hovertemplate=f"sampling {r['phase_ui']:+.4f} UI<extra>lane {r['lane']}</extra>"))
    fig.add_hline(y=lt, line=dict(color=RED, dash="dash", width=1), annotation_text=f"target {target_ber:.0e}",
                  annotation_position="top left", annotation_font=dict(size=11, color=RED))
    fig.update_xaxes(title_text="sampling phase [UI] from the pulse reference", range=[-0.55, 0.55])
    fig.update_yaxes(title_text="log10 BER", range=[FLOOR - 2, 1])
    fig.update_layout(showlegend=len(lanes) <= 8)
    return fig


def tornado_figure(sens: dict, height: int | None = None) -> go.Figure:
    """Each knob's worst-lane margin at -20 % and +20 % as a bar through the
    nominal; the verdict boundary at 0; sorted by how far the two sides
    reach. Margin = min(eye height, eye width) relative to its target."""
    rows = sorted(sens["rows"], key=lambda r: -max(abs(r["low"]["margin"] - sens["nominal"]["margin"]),
                                                  abs(r["high"]["margin"] - sens["nominal"]["margin"])))
    height = height or (70 + 26 * len(rows))
    fig = go.Figure(layout=_base(height, margin=dict(l=190, r=16, t=22, b=40)))
    nom = sens["nominal"]["margin"]
    labels = [f"{r['label']}  [{r['source']}]" for r in rows]
    for side, color, name in (("low", "#9ca3af", "−20 % (targets −10 mV / −0.05 UI)"), ("high", "#374151", "+20 %")):
        xs = [r[side]["margin"] - nom for r in rows]
        fig.add_trace(go.Bar(y=labels, x=xs, base=[nom] * len(rows), orientation="h", name=name,
                             marker=dict(color=color), width=0.55,
                             customdata=[[r[side]["value"], r[side]["margin"], "PASS" if r[side]["passes"] else "FAIL"] for r in rows],
                             hovertemplate="%{y}<br>value %{customdata[0]:.4g} → margin %{customdata[1]:+.3f} %{customdata[2]}<extra></extra>"))
    fig.add_vline(x=nom, line=dict(color=BLUE, width=1, dash="dot"), annotation_text=f"nominal {nom:+.3f}",
                  annotation_position="bottom left", annotation_font=dict(size=11, color=BLUE))
    fig.add_vline(x=0.0, line=dict(color=RED, width=1.5), annotation_text="verdict boundary", annotation_position="top right",
                  annotation_font=dict(size=11, color=RED))
    # the axis follows the knobs near the boundary; a far-off side (the eye-height
    # target of a link failing on width sits at +3.8) runs off the edge, which
    # the hover still reports
    near = [m for r in rows for m in (r["low"]["margin"], r["high"]["margin"]) if abs(m - nom) <= 0.5] or [nom]
    lo, hi = min(near), max(near)
    pad = 0.15 * max(hi - lo, 0.05)
    fig.add_vrect(x0=0.0, x1=max(hi, 0.0) + pad, fillcolor="#dcfce7", opacity=0.35, line_width=0, layer="below")
    fig.update_xaxes(title_text="worst-lane margin, min(eye height, eye width) relative to target",
                     range=[min(lo, 0.0) - pad, max(hi, 0.0) + pad])
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(barmode="overlay", legend=dict(orientation="h", y=1.1, x=0))
    return fig


__all__ = ["bathtub_figure", "tornado_figure", "FLOOR"]
