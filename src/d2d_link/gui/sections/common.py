"""Small pieces every section uses: source chips, number formatting."""

from __future__ import annotations

from dash import html

SOURCE_TITLE = {
    "survey": "from the survey table (unverified: no specification text yet)",
    "model": "a model estimate (source: model), not a specification value",
    "config": "set by this config",
    "yaml": "set in the config file",
    "override": "edited on this page",
    "default": "the schema's default",
    "spec": "quoted from the specification text",
}


def chip(source: str) -> html.Span:
    return html.Span(source, className=f"chip chip-{source}", title=SOURCE_TITLE.get(source, source))


def fmt(v: float | None, digits: int = 1, unit: str = "") -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}{(' ' + unit) if unit else ''}"


def verdict_badge(passes: bool, big: bool = False) -> html.Span:
    return html.Span("✔ PASS" if passes else "✘ FAIL",
                     className=("badge " + ("pass" if passes else "fail")) + (" big" if big else ""))


def section(anchor: str, number: str, title: str, aside: str | None, *children) -> html.Section:
    head = [html.Span(number, className="num"), html.H2(title)]
    if aside:
        head.append(html.Span(aside, className="aside"))
    return html.Section([html.Div(head, className="sec-head"), *children], id=f"sec-{anchor}", className="sec")


__all__ = ["chip", "fmt", "verdict_badge", "section"]
