"""Section 1 -- the verdict: three tiles (eye width, eye height, BER on
their binding lanes), one eye-width bar per lane against the target, and a
sentence saying whether this is a timing or an amplitude verdict."""

from __future__ import annotations

from dash import html

from .common import chip, section


def verdict(result: dict) -> html.Section:
    rep, lanes = result["report"], result["lanes"]
    t = rep["targets"]
    ew_t, eh_t, ber_t = t["eye_width_ui"], t["eye_height_mv"], t["ber"]
    lw = min(lanes, key=lambda r: r["eye_width_ui"])
    lh = min(lanes, key=lambda r: r["eye_height_v"])
    lb = max(lanes, key=lambda r: r["log10_ber"])
    ew_ok = lw["eye_width_ui"] >= ew_t["value"]
    eh_ok = 1e3 * lh["eye_height_v"] >= eh_t["value"]
    import math
    ber_ok = lb["log10_ber"] <= math.log10(ber_t["value"])

    def tile(title, big, unit, ok, target_txt, src, margin_txt):
        return html.Div([
            html.Div([html.Span(title), html.Span("✔" if ok else "✘ FAIL", className="ok" if ok else "fail")],
                     className="tile-head"),
            html.Div([html.B(big), html.Span(" " + unit)], className="tile-big"),
            html.Div([html.Span("target " + target_txt + " "), chip(src), html.Span(" " + margin_txt)],
                     className="tile-foot"),
        ], className="tile " + ("tile-ok" if ok else "tile-fail"))

    tiles = html.Div([
        tile(f"min eye width · lane {lw['lane']}", f"{lw['eye_width_ui']:.3f}", "UI", ew_ok,
             f"{ew_t['value']:g} UI", ew_t["source"], f"{lw['eye_width_margin_ui']:+.3f} UI"),
        tile(f"min eye height · lane {lh['lane']}", f"{1e3 * lh['eye_height_v']:.1f}", "mV", eh_ok,
             f"{eh_t['value']:g} mV", eh_t["source"], f"{lh['eye_height_margin_mv']:+.1f} mV"),
        tile(f"worst BER · lane {lb['lane']}", f"10^{lb['log10_ber']:.1f}", "", ber_ok,
             f"{ber_t['value']:.0e}", ber_t["source"], "at the sampling phase"),
    ], className="tiles")

    lo = min(min(r["eye_width_ui"] for r in lanes), ew_t["value"]) - 0.03
    hi = max(max(r["eye_width_ui"] for r in lanes), ew_t["value"]) + 0.03
    span = max(hi - lo, 1e-6)
    bars = []
    for r in sorted(lanes, key=lambda r: r["lane"]):
        w = 100.0 * (r["eye_width_ui"] - lo) / span
        bars.append(html.Div([
            html.Span(f"lane {r['lane']}", className="bar-lbl"),
            html.Span(f"{r['n_aggressors']} aggr.", className="bar-sub"),
            html.Div([html.Div(className="bar-fill " + ("ok" if r["eye_width_ui"] >= ew_t["value"] else "fail"),
                               style={"width": f"{w:.1f}%"}),
                      html.Span(f"{r['eye_width_ui']:.3f}", className="bar-val", style={"left": f"{w:.1f}%"})],
                     className="bar-trk"),
        ], className="bar-row"))
    tgt = 100.0 * (ew_t["value"] - lo) / span
    bars.append(html.Div([html.Span("", className="bar-lbl"), html.Span("", className="bar-sub"),
                          html.Div([html.Div(className="bar-target", style={"left": f"{tgt:.1f}%"}),
                                    html.Span(f"target {ew_t['value']:g} UI ({ew_t['source']})", className="bar-tgt-lbl",
                                              style={"left": f"{tgt:.1f}%"})], className="bar-trk bar-trk-tgt")],
                         className="bar-row"))

    n_fail_w = sum(r["eye_width_ui"] < ew_t["value"] for r in lanes)
    n_fail_h = sum(1e3 * r["eye_height_v"] < eh_t["value"] for r in lanes)
    if result["passes"]:
        kind = ("timing" if lw["eye_width_margin_ui"] / ew_t["value"] < lh["eye_height_margin_mv"] / eh_t["value"]
                else "amplitude")
        sentence = (f"Every lane passes. The thinnest margin is {kind}: lane {lw['lane']} keeps "
                    f"{lw['eye_width_margin_ui']:+.3f} UI of eye width, lane {lh['lane']} {lh['eye_height_margin_mv']:+.1f} mV "
                    f"of eye height; the verdict is a {kind} verdict.")
    else:
        what = []
        if n_fail_w:
            what.append(f"eye width fails on {n_fail_w} of {len(lanes)} lanes (lane {lw['lane']} by "
                        f"{-lw['eye_width_margin_ui']:.3f} UI)")
        if n_fail_h:
            what.append(f"eye height fails on {n_fail_h} lanes (lane {lh['lane']} by {-lh['eye_height_margin_mv']:.1f} mV)")
        if not n_fail_h and n_fail_w:
            what.append(f"eye height is {1e3 * lh['eye_height_v'] / eh_t['value']:.1f}× its target, so the verdict is a timing verdict")
        if result.get("unrepaired"):
            what.append(f"unrepaired failed lanes {result['unrepaired']}")
        sentence = "; ".join(what) + "."
    aside = ("targets resolve to the survey table: none set in the YAML" if all(v["source"] == "survey" for v in t.values())
             else "targets: " + ", ".join(f"{k} {v['source']}" for k, v in t.items()))
    return section("verdict", "1", "Verdict", aside, tiles, html.Div(bars, className="bars"),
                   html.P(sentence, className="note"))


__all__ = ["verdict"]
