"""Section 2 -- what flips the verdict: the sensitivity run (every model
and survey knob +-20 %) as a sentence, a tornado and a table. It is a
separate job (1 + 2 x knobs runs); until it has run, the section offers it."""

from __future__ import annotations

from dash import dcc, html

from ..figures import tornado_figure
from .common import chip, section


def flips(result: dict, sens_job, n_runs: int, est_s: float | None) -> html.Section:
    verdict = "PASS" if result["passes"] else "FAIL"
    if sens_job is None or sens_job.status in ("failed", "cancelled"):
        est = f" · ~{est_s:.0f} s" if est_s else ""
        body = [html.P([f"Every model estimate and survey number this verdict leans on, moved −20 % / +20 % "
                        f"(targets −/+ 10 mV, 0.05 UI), the link rerun each time: {n_runs} runs{est}. ",
                        html.Button("Run sensitivity", id={"type": "action", "name": "sensitivity"}, n_clicks=0, className="btn primary")], className="note")]
        if sens_job is not None and sens_job.error:
            body.append(html.P(f"last attempt failed: {sens_job.error}", className="fine"))
        return section("flips", "2", "What flips the verdict", "not run yet", *body)
    if sens_job.status in ("queued", "running"):
        done, total = sens_job.progress or (0, n_runs)
        return section("flips", "2", "What flips the verdict", f"running · {done} / {total} runs",
                       html.Div(html.Div(className="pbar-fill", style={"width": f"{100.0 * done / max(total, 1):.0f}%"}),
                                className="pbar"),
                       html.P("The page keeps its numbers while the sensitivity runs land.", className="fine"))
    sens = sens_job.result["sensitivity"]
    rows = sens["rows"]
    flipping = [r for r in rows if r["flips"]]
    nom = sens["nominal"]["margin"]
    closest = sorted(rows, key=lambda r: min(abs(r["low"]["margin"]), abs(r["high"]["margin"])))[:3]

    def nearest(r):
        side = "low" if abs(r["low"]["margin"]) < abs(r["high"]["margin"]) else "high"
        return f"{r['label']} {r[side]['value']:.4g} ({r[side]['margin']:+.3f})"

    if flipping:
        sentence = html.P([html.B(f"{len(flipping)} estimate(s) flip this {verdict}: "),
                           ", ".join(f"{r['label']} [{r['source']}]" for r in flipping),
                           f". Nominal margin {nom:+.3f}."], className="note callout")
    else:
        sentence = html.P([html.B(f"No single ±20 % estimate flips this {verdict}. "),
                           f"Nominal margin {nom:+.3f}; closest to the boundary: " + "; ".join(nearest(r) for r in closest) + "."],
                          className="note callout")
    table = html.Table([html.Thead(html.Tr([html.Th(h) for h in ("parameter", "source", "nominal", "−20 % → verdict (margin)",
                                                                 "+20 % → verdict (margin)", "flips")])),
                        html.Tbody([html.Tr([html.Td(r["label"]), html.Td(chip(r["source"])), html.Td(f"{r['nominal']:.4g}"),
                                             html.Td(f"{r['low']['value']:.4g} → {'PASS' if r['low']['passes'] else 'FAIL'} ({r['low']['margin']:+.3f})",
                                                     className="ok" if r["low"]["passes"] else "fail"),
                                             html.Td(f"{r['high']['value']:.4g} → {'PASS' if r['high']['passes'] else 'FAIL'} ({r['high']['margin']:+.3f})",
                                                     className="ok" if r["high"]["passes"] else "fail"),
                                             html.Td("yes" if r["flips"] else "no", className="fail" if r["flips"] else "")])
                                    for r in rows])], className="lanes sens")
    return section("flips", "2", "What flips the verdict",
                   f"each estimate −20 % ○ / +20 % ● · {sens_job.result.get('elapsed_s', 0):.0f} s",
                   sentence, dcc.Graph(figure=tornado_figure(sens), config={"displayModeBar": False}), table)


__all__ = ["flips"]
