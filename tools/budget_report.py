"""The timing budget of a link, lane by lane, as a Markdown (or JSON) report.

    python tools/budget_report.py configs/standard_32g_x16_module.yaml
    python tools/budget_report.py configs/standard_32g_x1.yaml -o budget.md
    python tools/budget_report.py configs/standard_32g_x1.yaml --json budget.json

Everything comes from the config and the statistical engine (invariant #1,
#3): the clock-path budget in fs and UI by origin (Tx PLL leak, local PLL,
path noise, wander, tree, quantisation), the per-lane eye height and width
at the target BER against the targets with their source (invariant #5), the
crosstalk each lane sees and how the lanes were mapped after repair. The
report is the deliverable a "timing budget" asks for; the examples print the
same numbers in prose.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def budget_rows(cfg, clock) -> list[tuple[str, float]]:
    b = clock.budget()
    rows = [("Tx PLL common-mode leak (tree, local PLL, rho)", b.common_leak_s),
            ("local PLL own noise above its loop", b.local_pll_s),
            ("data path white jitter", b.data_path_s),
            ("data path wander", b.data_wander_s),
            ("clock path white jitter", b.clock_path_s),
            ("clock path wander", b.clock_wander_s),
            ("receive tree jitter", b.tree_s),
            ("phase-interpolator quantisation (uniform)", clock.quantisation_sigma_s())]
    return rows


def report(cfg, res, clock) -> dict:
    from d2d_link.channel.coupled import describe

    ui = cfg.ui
    rows = budget_rows(cfg, clock)
    total = math.sqrt(sum(v ** 2 for _, v in rows))
    lm = res.lanes
    t = res.targets
    out = {
        "link": {"data_rate_gtps": cfg.data_rate_gtps, "package": cfg.package.kind,
                 "length_mm": cfg.channel.length_mm, "ui_ps": ui * 1e12,
                 "forwarded_clock_ghz": cfg.forwarded_clock_hz / 1e9,
                 "lanes_requested": lm.requested_width, "lanes_active": lm.active_width,
                 "repair": lm.mode, "failed": list(lm.failed), "unrepaired": list(lm.unrepaired),
                 "insertion_loss_nyquist_db": res.stat[0].extras["insertion_loss_nyquist_db"] if res.stat else None,
                 "tx_pll_rms_fs": 1e15 * clock.pll_rms_s(),
                 "local_pll_rms_fs": 1e15 * clock.local_pll_rms_s(),
                 "verdict": "PASS" if res.passes else "FAIL"},
        "jitter_budget": [{"term": name, "fs": 1e15 * v, "ui": v / ui} for name, v in rows]
                         + [{"term": "total (power sum)", "fs": 1e15 * total, "ui": total / ui}],
        "targets": {k: {"value": v, "source": src} for k, (v, src) in t.items()},
        "crosstalk": ({"mode": cfg.channel.xtalk, **describe(cfg)} if cfg.channel.xtalk == "coupled"
                      else {"mode": cfg.channel.xtalk, "adjacent_db": cfg.xtalk_db()[0] if cfg.channel.xtalk != "none" else None}),
        "lanes": [{"logical": r.lane, "physical": lm.logical_to_physical[r.lane],
                   "skew_ps": float(res.skew_ps[lm.logical_to_physical[r.lane]]),
                   "skew_residual_ui": r.skew_residual_ui, "aggressors": r.extras["n_aggressors"],
                   "xtalk_rms_mv": 1e3 * r.extras["xtalk_rms_v"],
                   "eye_height_mv": 1e3 * r.eye_height_v, "eye_width_ui": r.eye_width_ui,
                   "eye_height_margin_mv": r.eye_height_margin_mv, "eye_width_margin_ui": r.eye_width_margin_ui,
                   "eye_width_clipped": bool(r.extras.get("eye_width_clipped", False)),
                   "log10_ber": r.log10_ber, "ber": r.ber, "passes": r.passes} for r in res.stat],
    }
    return out


def to_markdown(rep: dict) -> str:
    L = rep["link"]
    lines = [f"# Timing budget: {L['package']} package, {L['data_rate_gtps']:g} GT/s, {L['length_mm']:g} mm, "
             f"{L['lanes_active']}/{L['lanes_requested']} lanes -- {L['verdict']}", "",
             f"UI {L['ui_ps']:.3f} ps, forwarded clock {L['forwarded_clock_ghz']:g} GHz DDR, insertion loss "
             f"{L['insertion_loss_nyquist_db']:.2f} dB at Nyquist; repair {L['repair']}, failed {L['failed']}"
             + (f", UNREPAIRED {L['unrepaired']}" if L["unrepaired"] else "") + ".", "",
             f"Tx PLL in band {L['tx_pll_rms_fs']:.1f} fs RMS; local PLL {L['local_pll_rms_fs']:.1f} fs.", "",
             "## Clock-path jitter at the sampler (RMS, closed form)", "",
             "| term | fs | UI |", "|---|---:|---:|"]
    for row in rep["jitter_budget"]:
        lines.append(f"| {row['term']} | {row['fs']:.1f} | {row['ui']:.4f} |")
    lines += ["", "## Targets", "", "| quantity | value | source |", "|---|---:|---|"]
    for k, v in rep["targets"].items():
        lines.append(f"| {k} | {v['value']:g} | {v['source']} |")
    x = rep["crosstalk"]
    lines += ["", "## Crosstalk", ""]
    if x["mode"] == "coupled":
        lines.append(f"Coupled-line estimate: pitch {x['pitch_um']:g} um (source: {x['pitch_source']}), width "
                     f"{x['trace_width_um']:g} um, height {x['dielectric_height_um']:g} um, eps_r {x['eps_r']:g} "
                     f"(eps_eff {x['eps_eff']:.2f}); FEXT at Nyquist {x['fext_adjacent_db']:.1f} dB nearest, "
                     f"{x['fext_second_db']:.1f} dB second neighbour. A model estimate, not a specification value.")
    elif x["mode"] == "fext":
        lines.append(f"Behavioural FEXT level {x['adjacent_db']:.1f} dB at Nyquist (nearest neighbour).")
    else:
        lines.append("Off.")
    lines += ["", "## Lanes", "",
              "| logical | physical | skew [ps] | residual [UI] | aggressors | xtalk [mV] | eye height [mV] | "
              "eye width [UI] | margin EH [mV] | margin EW [UI] | log10 BER | pass |",
              "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in rep["lanes"]:
        clipped = " (clipped)" if r["eye_width_clipped"] else ""
        lines.append(f"| {r['logical']} | {r['physical']} | {r['skew_ps']:.2f} | {r['skew_residual_ui']:+.4f} | "
                     f"{r['aggressors']} | {r['xtalk_rms_mv']:.2f} | {r['eye_height_mv']:.1f} | {r['eye_width_ui']:.3f}{clipped} | "
                     f"{r['eye_height_margin_mv']:+.1f} | {r['eye_width_margin_ui']:+.3f} | {r['log10_ber']:.1f} | "
                     f"{'yes' if r['passes'] else 'no'} |")
    return "\n".join(lines) + "\n"


def build(cfg):
    from d2d_link.clock.forwarded import ForwardedClock
    from d2d_link.engine import run_link

    return report(cfg, run_link(cfg), ForwardedClock(cfg))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="Markdown file (default: stdout)")
    ap.add_argument("--json", type=Path, help="also write the report as JSON")
    args = ap.parse_args(argv)
    from d2d_link.config import load_config

    rep = build(load_config(args.config))
    md = to_markdown(rep)
    if args.out:
        args.out.write_text(md, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(md)
    if args.json:
        args.json.write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
