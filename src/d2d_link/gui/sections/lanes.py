"""Section 5 -- lanes and repair: the lane table sorted by eye-width margin,
with the mapping after repair. The physical floor plan with per-lane eyes
joins in G2; the table is the record."""

from __future__ import annotations

from dash import html

from .common import section


def lanes_table(result: dict) -> html.Table:
    rep = result["report"]
    by_lane = {r["logical"]: r for r in rep["lanes"]}
    rows = sorted(result["lanes"], key=lambda r: (r["margin"], r["lane"]))
    head = html.Tr([html.Th(h) for h in ("logical", "physical", "skew [ps]", "resid. [UI]", "aggr.", "xtalk [mV]",
                                           "eye H [mV]", "eye W [UI]", "margin EH", "margin EW", "log10 BER", "pass")])
    body = []
    for r in rows:
        L = by_lane[r["lane"]]
        cls = "worst" if r["lane"] == result["worst_lane"] else ""
        body.append(html.Tr([
            html.Td(f"L{r['lane']}"), html.Td(f"P{r['physical']}"), html.Td(f"{L['skew_ps']:+.2f}"),
            html.Td(f"{r['skew_residual_ui']:+.4f}"), html.Td(str(r["n_aggressors"])),
            html.Td(f"{1e3 * r['xtalk_rms_v']:.2f}"), html.Td(f"{1e3 * r['eye_height_v']:.1f}"),
            html.Td(f"{r['eye_width_ui']:.3f}"), html.Td(f"{r['eye_height_margin_mv']:+.1f}"),
            html.Td(f"{r['eye_width_margin_ui']:+.3f}"), html.Td(f"{r['log10_ber']:.1f}"),
            html.Td("✔ yes" if r["passes"] else "✘ no", className="ok" if r["passes"] else "fail"),
        ], className=cls, id={"type": "lane-row", "lane": r["lane"]}))
    return html.Table([html.Thead(head), html.Tbody(body)], className="lanes")


def lanes(result: dict) -> html.Section:
    n_fail = len(result.get("failed") or [])
    repair = result["repair"]
    summary = (f"{result['active']} of {result['requested']} lanes active; repair {repair}; "
               f"failed physical lanes {result.get('failed') or []}"
               + (f"; UNREPAIRED {result['unrepaired']}" if result.get("unrepaired") else ""))
    if repair == "width_degrade" and n_fail:
        summary += ". Width degradation keeps the largest working power-of-two block; its neighbours are re-derived."
    elif repair == "spare" and n_fail:
        summary += ". Logical lanes are remapped past the failures onto the spares; physical adjacency changes."
    return section("lanes", "5", "Lanes and repair", f"{len(result['lanes'])} rows · sorted by margin · worst lane highlighted",
                   html.P(summary, className="note"), lanes_table(result))


__all__ = ["lanes", "lanes_table"]
