"""Section 4 -- the bathtubs of every lane on one axis, the selected lane
(clicked on the floor plan or the table) in front."""

from __future__ import annotations

from dash import dcc, html

from ..figures import FLOOR, bathtub_figure
from .common import section


def eyes(result: dict, selected: int | None) -> html.Section:
    lanes = result["lanes"]
    target = result["report"]["targets"]["ber"]["value"]
    sel = next((r for r in lanes if r["lane"] == selected), None)
    aside = (f"lane {sel['lane']} in front · click a lane on the floor plan to change" if sel
             else f"{len(lanes)} lanes · click a lane on the floor plan to bring one in front")
    fig = bathtub_figure(lanes, target, selected, height=320)
    note = (f"The eye's edges are found on this curve by regula falsi at BER {target:.0e}; the opening between them is the "
            f"eye width, its centre the sampling phase (the diamond). Depths below 10^{FLOOR:.0f} are drawn flat: the "
            "bathtub's bottom is set by the jitter kernel's reach, not by physics.")
    return section("eyes", "4", "Eye & bathtub per lane", aside,
                   dcc.Graph(figure=fig, config={"displayModeBar": False}), html.P(note, className="fine"))


__all__ = ["eyes"]
