"""The headline sentence: every underlined value is a control.

``Standard package, 32 GT/s, 25 mm, 5 / 5 lanes, coupled crosstalk ✘ FAIL``
-- package, rate, length, lane count, crosstalk mode and routing are inputs
whose change becomes an override and a re-run. The paragraph under it is the
report's first lines (UI, forwarded clock, insertion loss, the clock's own
jitter, the crosstalk estimate) with their sources.
"""

from __future__ import annotations

from dash import dcc, html

from ...spec import survey
from .common import chip, verdict_badge


def _inline_dropdown(path: str, value, options: list, width: str = "9em") -> dcc.Dropdown:
    return dcc.Dropdown(id={"type": "headline", "path": path}, value=value, clearable=False, searchable=False,
                        options=[{"label": str(o), "value": o} for o in options],
                        className="inline-dd", style={"width": width})


def _inline_number(path: str, value, step: float, width: str = "5em") -> dcc.Input:
    return dcc.Input(id={"type": "headline", "path": path}, value=value, type="number", step=step, debounce=True,
                     className="inline-num", style={"width": width})


def headline(cfg, result: dict | None) -> html.Div:
    rates = [float(r) for r in survey("data_rates_gtps").value]
    lanes = cfg.lanes.count
    active = f"{result['active']} / {result['requested']}" if result else f"{lanes} / {lanes}"
    parts = [
        _inline_dropdown("package.kind", cfg.package.kind, ["standard", "advanced"], "9.5em"),
        html.Span(" package, "),
        _inline_dropdown("data_rate_gtps", cfg.data_rate_gtps, rates, "6.5em"),
        html.Span(" GT/s, "),
        _inline_number("channel.length_mm", cfg.channel.length_mm, 0.5),
        html.Span(" mm, "),
        _inline_number("lanes.count", cfg.lanes.count, 1, "4em"),
        html.Span(f" lanes ({active} active), "),
        _inline_dropdown("channel.xtalk", cfg.channel.xtalk, ["none", "fext", "coupled", "touchstone"], "8.5em"),
        html.Span(" crosstalk, "),
        _inline_dropdown("channel.routing", cfg.channel.routing, ["microstrip", "stripline"], "9em"),
        html.Span(" "),
    ]
    if result:
        parts.append(verdict_badge(result["passes"], big=True))
    else:
        parts.append(html.Span("not run yet", className="badge pending big"))
    return html.Div(parts, className="headline")


def lede(cfg, result: dict | None) -> html.P:
    if not result:
        return html.P("Run the link to fill this page; every number on it comes from the statistical engine "
                      "and carries its source.", className="lede")
    L = result["report"]["link"]
    il = L["insertion_loss_nyquist_db"]
    bits = [f"UI {L['ui_ps']:.3f} ps, forwarded clock {L['forwarded_clock_ghz']:g} GHz DDR, "
            f"insertion loss {il:.2f} dB at Nyquist; repair {L['repair']}, failed {L['failed']}. "
            f"Tx PLL in band {L['tx_pll_rms_fs']:.1f} fs RMS; local PLL {L['local_pll_rms_fs']:.1f} fs. "]
    x = result["report"]["crosstalk"]
    kids: list = [html.Span("".join(bits))]
    if x["mode"] == "coupled":
        kids += [html.Span(f"Coupled-line estimate: pitch {x['pitch_um']:g} µm "), chip(x["pitch_source"]),
                 html.Span(f", width {x['trace_width_um']:g} µm, height {x['dielectric_height_um']:g} µm, "
                           f"ε_r {x['eps_r']:g} "), chip("model"),
                 html.Span(f" (ε_eff {x['eps_eff']:.2f}) give FEXT {x['fext_adjacent_db']:.1f} dB nearest, "
                           f"{x['fext_second_db']:.1f} dB second neighbour.")]
    elif x["mode"] == "fext":
        kids += [html.Span(f"Behavioural FEXT {x['adjacent_db']:.1f} dB at Nyquist, nearest lane "),
                 chip(x["adjacent_source"]), html.Span(".")]
    else:
        kids.append(html.Span("Crosstalk off."))
    return html.P(kids, className="lede")


__all__ = ["headline", "lede"]
