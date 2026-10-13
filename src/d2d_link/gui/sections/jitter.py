"""Section 3 -- the clock-path jitter at the sampler: one bar per term in fs
with its share of the variance, the power-sum total, and the forwarded
clock's one-line story (what the Tx PLL would have added, what leaked)."""

from __future__ import annotations

from dash import html

from .common import section


def jitter(result: dict) -> html.Section:
    rep = result["report"]
    rows = [r for r in rep["jitter_budget"] if not r["term"].startswith("total")]
    total = next(r for r in rep["jitter_budget"] if r["term"].startswith("total"))
    tot2 = max(total["fs"] ** 2, 1e-30)
    top = max((r["fs"] for r in rows), default=1.0) or 1.0
    bars = []
    for r in sorted(rows, key=lambda r: -r["fs"]):
        share = 100.0 * r["fs"] ** 2 / tot2
        bars.append(html.Div([
            html.Span(r["term"], className="jb-lbl"),
            html.Div(html.Div(className="jb-fill", style={"width": f"{100.0 * r['fs'] / top:.1f}%"}), className="jb-trk"),
            html.Span(f"{r['fs']:.1f}", className="jb-num"),
            html.Span(f"{share:.1f} %", className="jb-share"),
        ], className="jb-row"))
    bars.append(html.Div([html.Span("total (power sum)", className="jb-lbl total"),
                          html.Div(className="jb-trk"),
                          html.Span(f"{total['fs']:.1f} fs = {total['ui']:.4f} UI", className="jb-num total"),
                          html.Span("100 %", className="jb-share")], className="jb-row jb-total"))
    L = rep["link"]
    leak = next((r["fs"] for r in rows if "leak" in r["term"]), 0.0)
    story = (f"Forwarded-clock tracking: the Tx PLL's {L['tx_pll_rms_fs']:.1f} fs in band would all reach the "
             f"sampler from an independent clock; data and clock share the PLL, so only {leak:.1f} fs leak "
             f"through the tree's delay and bandwidth, and the tracker removes the common part below its bandwidth.")
    spurs = L.get("spur_terms") or []
    if spurs:
        story += f" {len(spurs)} profile spurs enter as sinusoids ({max(s['amplitude_fs'] for s in spurs):.1f} fs largest)."
    return section("jitter", "3", "Clock-path jitter at the sampler", "RMS, closed form · each bar adds in power, not in fs",
                   html.Div(bars, className="jb"), html.P(story, className="note"))


__all__ = ["jitter"]
