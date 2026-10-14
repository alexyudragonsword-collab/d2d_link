"""Compare with: this page's run beside another scenario's, the numbers that
decide the verdict side by side and the per-lane eye widths of both."""

from __future__ import annotations

from dash import html

from .common import section, verdict_badge


def _worst(result: dict) -> dict:
    return next(r for r in result["lanes"] if r["lane"] == result["worst_lane"])


def compare(mine: dict, other: dict, my_name: str, other_name: str, other_job) -> html.Section:
    if other is None:
        state = "running" if other_job is not None and other_job.status in ("queued", "running") else "not run"
        return section("compare", "·", "Compare with", f"{other_name}: {state}",
                       html.P(f"{other_name} is {state}; the comparison fills in when its run lands.", className="note"))
    a, b = _worst(mine), _worst(other)
    ra, rb = mine["report"], other["report"]
    L = (ra["link"], rb["link"])

    def row(label, va, vb, fmt="{}"):
        return html.Tr([html.Td(label, className="lbl"), html.Td(fmt.format(va)), html.Td(fmt.format(vb))])

    rows = [
        html.Tr([html.Td("verdict", className="lbl"), html.Td(verdict_badge(mine["passes"])), html.Td(verdict_badge(other["passes"]))]),
        row("link", f"{L[0]['package']} · {L[0]['data_rate_gtps']:g} GT/s · {L[0]['length_mm']:g} mm",
            f"{L[1]['package']} · {L[1]['data_rate_gtps']:g} GT/s · {L[1]['length_mm']:g} mm"),
        row("lanes active", f"{mine['active']} / {mine['requested']} · {mine['repair']}", f"{other['active']} / {other['requested']} · {other['repair']}"),
        row("insertion loss at Nyquist", L[0]["insertion_loss_nyquist_db"], L[1]["insertion_loss_nyquist_db"], "{:.2f} dB"),
        row("clock residual (total)", ra["jitter_budget"][-1]["fs"], rb["jitter_budget"][-1]["fs"], "{:.1f} fs"),
        row("worst lane", f"L{a['lane']} (P{a['physical']})", f"L{b['lane']} (P{b['physical']})"),
        row("worst-lane eye height", 1e3 * a["eye_height_v"], 1e3 * b["eye_height_v"], "{:.1f} mV"),
        row("worst-lane eye width", a["eye_width_ui"], b["eye_width_ui"], "{:.3f} UI"),
        row("worst-lane margin", a["margin"], b["margin"], "{:+.3f}"),
        row("crosstalk", ra["crosstalk"]["mode"], rb["crosstalk"]["mode"]),
        row("run time", mine["elapsed_s"], other["elapsed_s"], "{:.1f} s"),
    ]
    table = html.Table([html.Thead(html.Tr([html.Th(""), html.Th(my_name), html.Th(other_name)])), html.Tbody(rows)],
                       className="lanes cmp")
    n = max(len(mine["lanes"]), len(other["lanes"]))
    lo = min(min(r["eye_width_ui"] for r in mine["lanes"] + other["lanes"]), ra["targets"]["eye_width_ui"]["value"]) - 0.03
    hi = max(max(r["eye_width_ui"] for r in mine["lanes"] + other["lanes"]), ra["targets"]["eye_width_ui"]["value"]) + 0.03
    span = max(hi - lo, 1e-6)
    bars = []
    for i in range(n):
        cells = [html.Span(f"lane {i}", className="bar-lbl")]
        for res, cls in ((mine, "a"), (other, "b")):
            r = next((q for q in res["lanes"] if q["lane"] == i), None)
            if r is None:
                cells.append(html.Div(className="bar-trk cmp-trk"))
                continue
            w = 100.0 * (r["eye_width_ui"] - lo) / span
            cells.append(html.Div([html.Div(className=f"bar-fill cmp-{cls} " + ("ok" if r["passes"] else "fail"), style={"width": f"{w:.1f}%"}),
                                   html.Span(f"{r['eye_width_ui']:.3f}", className="bar-val", style={"left": f"{w:.1f}%"})],
                                  className="bar-trk cmp-trk"))
        bars.append(html.Div(cells, className="bar-row cmp-row"))
    return section("compare", "·", "Compare with", f"{other_name} · eye widths per lane, left = this page",
                   table, html.Div(bars, className="bars"))


__all__ = ["compare"]
