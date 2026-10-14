"""Section 5 -- lanes and repair: the physical floor plan (one cell per
physical lane with its eye drawn to scale against the target mask; dead
bumps, idle halves and spares marked; the selected lane's aggressors
outlined) and the lane table sorted by margin."""

from __future__ import annotations

from dash import html

from .common import section


def floor_plan(result: dict, selected: int | None) -> html.Div:
    t = result["report"]["targets"]
    ew_t, eh_t = t["eye_width_ui"]["value"], t["eye_height_mv"]["value"]
    by_phys = {r["physical"]: r for r in result["lanes"]}
    failed = set(result.get("failed") or [])
    n_phys = result.get("physical_count") or (max(by_phys) + 1 if by_phys else 0)
    sel = next((r for r in result["lanes"] if r["lane"] == selected), None)
    aggr = set(sel["aggressors"]) if sel else set()
    cells = []
    for p in range(n_phys):
        r = by_phys.get(p)
        if r is None:
            kind = "dead" if p in failed else "idle"
            label = "✕ failed" if p in failed else ("spare" if p >= result["requested"] else "idle")
            cells.append(html.Div([html.Div(f"P{p}", className="fp-phys"), html.Div(label, className="fp-state")],
                                  className=f"fp-cell fp-{kind}" + (" fp-aggr" if p in aggr else "")))
            continue
        amp = max(2.0 * r["main_cursor_v"], 1e-9)             # a full eye spans +-main cursor
        w = 100.0 * min(r["eye_width_ui"], 1.0)
        h = 100.0 * min(r["eye_height_v"] / amp, 1.0)
        tw, th = 100.0 * ew_t, 100.0 * min(1e-3 * eh_t / amp, 1.0)
        ok = r["passes"]
        cls = "fp-cell fp-active" + (" fp-sel" if sel and r["lane"] == sel["lane"] else "") + (" fp-aggr" if p in aggr else "") \
            + (" fp-worst" if r["lane"] == result["worst_lane"] else "") + ("" if ok else " fp-fail")
        cells.append(html.Div([
            html.Div([html.Span(f"L{r['lane']}", className="fp-log"), html.Span(f"P{p}", className="fp-phys")], className="fp-head"),
            html.Div([html.Div(className="fp-eye " + ("ok" if ok else "fail"),
                               style={"width": f"{w:.1f}%", "height": f"{h:.1f}%"}),
                      html.Div(className="fp-mask", style={"width": f"{tw:.1f}%", "height": f"{th:.1f}%"})],
                     className="fp-box"),
            html.Div(f"{r['eye_width_ui']:.3f} UI · {1e3 * r['eye_height_v']:.0f} mV", className="fp-num"),
            html.Div(html.Div(className="fp-mbar " + ("ok" if ok else "fail"),
                              style={"width": f"{100.0 * min(max(r['margin'], 0.0), 0.2) / 0.2:.0f}%"}), className="fp-mtrk"),
        ], className=cls, id={"type": "lane-cell", "lane": r["lane"]}, n_clicks=0))
    legend = html.Div([
        html.Span([html.I(className="lg-eye"), " eye at the target BER, to scale (width = UI, height = fraction of ±main cursor)"]),
        html.Span([html.I(className="lg-mask"), f" target mask {ew_t:g} UI × {eh_t:g} mV"]),
        html.Span([html.I(className="lg-dead"), " failed bump"]), html.Span([html.I(className="lg-idle"), " idle / spare"]),
        html.Span([html.I(className="lg-aggr"), " aggressors of the selected lane"]),
    ], className="fp-legend")
    return html.Div([html.Div(cells, className="fp-grid", style={"gridTemplateColumns": f"repeat({min(n_phys, 16)}, 1fr)"}), legend])


def lanes_table(result: dict, selected: int | None) -> html.Table:
    rep = result["report"]
    by_lane = {r["logical"]: r for r in rep["lanes"]}
    rows = sorted(result["lanes"], key=lambda r: (r["margin"], r["lane"]))
    head = html.Tr([html.Th(h) for h in ("logical", "physical", "skew [ps]", "resid. [UI]", "aggr.", "xtalk [mV]",
                                           "eye H [mV]", "eye W [UI]", "margin EH", "margin EW", "log10 BER", "pass")])
    body = []
    for r in rows:
        L = by_lane[r["lane"]]
        cls = ("worst " if r["lane"] == result["worst_lane"] else "") + ("sel" if r["lane"] == selected else "")
        body.append(html.Tr([
            html.Td(f"L{r['lane']}"), html.Td(f"P{r['physical']}"), html.Td(f"{L['skew_ps']:+.2f}"),
            html.Td(f"{r['skew_residual_ui']:+.4f}"), html.Td(str(r["n_aggressors"])),
            html.Td(f"{1e3 * r['xtalk_rms_v']:.2f}"), html.Td(f"{1e3 * r['eye_height_v']:.1f}"),
            html.Td(f"{r['eye_width_ui']:.3f}"), html.Td(f"{r['eye_height_margin_mv']:+.1f}"),
            html.Td(f"{r['eye_width_margin_ui']:+.3f}"), html.Td(f"{r['log10_ber']:.1f}"),
            html.Td("✔ yes" if r["passes"] else "✘ no", className="ok" if r["passes"] else "fail"),
        ], className=cls.strip(), id={"type": "lane-row", "lane": r["lane"]}, n_clicks=0))
    return html.Table([html.Thead(head), html.Tbody(body)], className="lanes clickable")


def lanes(result: dict, selected: int | None = None) -> html.Section:
    n_fail = len(result.get("failed") or [])
    repair = result["repair"]
    summary = (f"{result['active']} of {result['requested']} lanes active; repair {repair}; "
               f"failed physical lanes {result.get('failed') or []}"
               + (f"; UNREPAIRED {result['unrepaired']}" if result.get("unrepaired") else ""))
    if repair == "width_degrade" and n_fail:
        summary += ". Width degradation keeps the largest working power-of-two block; its neighbours are re-derived."
    elif repair == "spare" and n_fail:
        summary += ". Logical lanes are remapped past the failures onto the spares; physical adjacency changes."
    return section("lanes", "5", "Lanes and repair",
                   f"{result.get('physical_count', len(result['lanes']))} physical · {len(result['lanes'])} active · click a lane",
                   html.P(summary, className="note"), floor_plan(result, selected), lanes_table(result, selected))


__all__ = ["lanes", "lanes_table", "floor_plan"]
