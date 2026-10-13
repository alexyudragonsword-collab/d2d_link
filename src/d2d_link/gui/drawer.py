"""The "All fields" drawer: the schema's 90-odd fields as a tree with a
value column and a source column, generated from ``config.form.SECTIONS``.
Groups are folded to a one-line summary by default; edits become overrides
and nothing else (a frozen ``LinkConfig`` is rebuilt from them)."""

from __future__ import annotations

from dash import dcc, html

from ..config.form import SECTIONS
from .sections.common import chip


def _control(row: dict):
    fid = {"type": "field", "path": row["path"]}
    kind, v = row["kind"], row["value"]
    if kind == "bool":
        return dcc.Checklist(id=fid, options=[{"label": "", "value": "on"}], value=["on"] if v else [],
                             className="fld-bool")
    if kind == "enum":
        return dcc.Dropdown(id=fid, value=v, clearable=False, searchable=False,
                            options=[{"label": o, "value": o} for o in row["options"]], className="fld-dd")
    if kind in ("float", "opt_float", "int", "opt_int"):
        return dcc.Input(id=fid, value="" if v is None else v, type="number", debounce=True,
                         placeholder="empty" if kind.startswith("opt") else None, className="fld-num")
    if kind in ("tuple_float", "tuple_int"):
        return dcc.Input(id=fid, value=" ".join(str(x) for x in (v or ())), type="text", debounce=True,
                         placeholder="e.g. 1 2 3", className="fld-text")
    return dcc.Input(id=fid, value="" if v is None else str(v), type="text", debounce=True,
                     placeholder="empty", className="fld-text")


def _summary(key: str, rows: list[dict]) -> str:
    vals = {r["path"]: r["value"] for r in rows}
    if key == "link":
        return f"{vals['data_rate_gtps']:g} GT/s · {vals['package.kind']}"
    if key == "channel":
        return f"{vals['channel.kind']} · {vals['channel.length_mm']:g} mm · {vals['channel.xtalk']}"
    if key == "lanes":
        return f"{vals['lanes.count']} · {vals['lanes.repair']}"
    if key == "clocking":
        tb = vals["clocking.track_bw_hz"]
        return f"tracker {tb:g} MHz" if tb is not None else "no tracker"
    if key == "tx":
        return f"{vals['tx.swing_vpp']:g} Vpp"
    if key == "rx":
        return f"{vals['rx.noise_rms_v']:g} mV @ {vals['rx.noise_at']}"
    if key == "sim":
        return f"{vals['sim.engine']} · osr {vals['sim.osr']}"
    if key == "target":
        return "survey table" if all(vals[p] is None for p in vals) else "set in config"
    return ""


def drawer(state, open_groups: set[str] | None = None) -> html.Div:
    rows = {r["path"]: r for r in state.rows()}
    open_groups = open_groups or set()
    groups = []
    for key, title, flds in SECTIONS:
        grp_rows = [rows[f["path"]] for f in flds]
        n_over = sum(1 for r in grp_rows if r["source"] == "override")
        head = html.Div([html.Span("▾" if key in open_groups else "▸", className="caret"), html.Span(title),
                         html.Span(_summary(key, grp_rows) + (f" · {n_over} edited" if n_over else ""), className="aside")],
                        className="grp-head", id={"type": "group", "key": key})
        body = []
        if key in open_groups:
            for r in grp_rows:
                body.append(html.Div([html.Span(r["label"], className="fld-lbl", title=r["path"]),
                                      _control(r), chip(r["source"])],
                                     className="fld-row" + (" edited" if r["source"] == "override" else "")))
        groups.append(html.Div([head, html.Div(body, className="grp-body")], className="grp"))
    n = len(state.overrides)
    foot = html.Div([html.Span(f"{n} field(s) differ from the file" if n else "no edits",
                               className="fine"),
                     html.Button("Discard edits", id="btn-discard", className="btn", disabled=not n),
                     html.Button("Re-run", id="btn-rerun-drawer", className="btn primary")], className="drawer-foot")
    return html.Div([html.Div(groups, className="drawer-body"), foot], className="drawer-inner")


def drawer_head() -> html.Div:
    """The static head with the close button: it lives outside the part the
    refresh callback re-renders, or every re-render would re-insert the
    button and fire the toggle callback (which closed the drawer each tick
    in the first G1 build)."""
    return html.Div([html.H3("All fields"),
                     html.Span([chip("yaml"), " ", chip("default"), " ", chip("model"), " ", chip("survey"),
                                " ", chip("override")], className="legend"),
                     html.Button("✕", id="btn-drawer-close", className="q-cancel")], className="drawer-head")


__all__ = ["drawer", "drawer_head"]
