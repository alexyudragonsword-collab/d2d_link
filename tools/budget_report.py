"""The timing budget of a link, lane by lane, as a Markdown (or JSON) report.

    python tools/budget_report.py configs/standard_32g_x16_module.yaml
    python tools/budget_report.py configs/standard_32g_x1.yaml -o budget.md
    python tools/budget_report.py configs/standard_32g_x1.yaml --json budget.json
    python tools/budget_report.py configs/standard_32g_x5_coupled.yaml --sensitivity

``--sensitivity`` answers "which guesses decide the verdict": every model
preset the config leans on (source: model -- trace resistance, loss tangent,
Z0, stack-up geometry, behavioural crosstalk level) and every survey number
it leans on (bump pitch for the coupled estimate; the eye-mask targets) is
moved by +-20 % (targets by +-10 mV / +-0.05 UI) and the link rerun; the
table lists the worst lane's margin on each side and marks the parameters
whose perturbation flips PASS/FAIL.

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
            ("profile spurs after the same leaks (sinusoids)", b.spur_s),
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
                 "local_pll_fn_hz": cfg.clocking.local_pll_fn_hz, "local_pll_bw_3db_hz": clock.local_pll_bw_3db_hz(),
                 "spur_terms": [{"f_hz": f0, "amplitude_fs": 1e15 * a} for f0, a in clock.spur_terms()],
                 "verdict": "PASS" if res.passes else "FAIL"},
        "jitter_budget": [{"term": name, "fs": 1e15 * v, "ui": v / ui} for name, v in rows]
                         + [{"term": "total (power sum)", "fs": 1e15 * total, "ui": total / ui}],
        "targets": {k: {"value": v, "source": src} for k, (v, src) in t.items()},
        "crosstalk": ({"mode": cfg.channel.xtalk, **describe(cfg)} if cfg.channel.xtalk == "coupled"
                      else {"mode": cfg.channel.xtalk, "adjacent_db": cfg.xtalk_db()[0] if cfg.channel.xtalk != "none" else None,
                            "adjacent_source": ("config" if cfg.channel.xtalk_adjacent_db is not None else "model")
                            if cfg.channel.xtalk != "none" else None}),
        "channel_model": ({"rlgc_source": "model", **{k: v for k, v in cfg.rlgc().items()}}
                          if cfg.channel.kind == "analytic" else {"file": cfg.channel.file}),
        "receiver": {"bw_hz": cfg.rx.bw_hz, "noise_at": cfg.rx.noise_at, "noise_rms_mv": 1e3 * cfg.rx.noise_rms_v,
                     "noise_gain": res.stat[0].extras["noise_gain"] if res.stat else None,
                     "sigma_sampler_mv": 1e3 * res.stat[0].sigma_noise_v if res.stat else None,
                     "ctle_peak_db": cfg.rx.ctle.peak_db if cfg.rx.ctle.enable else None,
                     "training_ber": cfg.rx.training_ber,
                     "centre_offset_ui": [r.extras["centre_offset_ui"] for r in res.stat]},
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
    rx = rep["receiver"]
    fe = "flat (an idealisation: no front-end pole)" if rx["bw_hz"] is None else f"{rx['bw_hz'] / 1e9:g} GHz first-order"
    where = (f"referred at the input in the Nyquist band, {rx['sigma_sampler_mv']:.2f} mV at the sampler "
             f"(front end x CTLE gain {rx['noise_gain']:.3f})" if rx["noise_at"] == "input"
             else "referred at the sampler (nothing shapes it)")
    ctle = f"CTLE {rx['ctle_peak_db']:g} dB peaking" if rx["ctle_peak_db"] is not None else "no CTLE"
    train = (f"training centres the eye at BER {rx['training_ber']:.0e}: offsets "
             + ", ".join(f"{o:+.4f}" for o in rx["centre_offset_ui"]) + " UI"
             if rx["training_ber"] is not None else "the sampler sits at the target opening's centre (ideal training)")
    lines += ["", "## Receiver", "",
              f"Front end {fe}; {ctle}; noise {rx['noise_rms_mv']:.2f} mV RMS {where}; {train}."]
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


def sensitivity_knobs(cfg) -> list[dict]:
    """The estimated and unverified numbers this config's verdict rests on:
    ``(label, config path, nominal, source, step)`` for each. A parameter the
    config sets explicitly is its own claim (source config) and still listed."""
    from d2d_link.channel.coupled import trace_pitch_um
    from d2d_link.config.schema import RLGC_PRESET_KEYS, STACKUP_KEYS

    ch = cfg.channel
    knobs = []
    if ch.kind == "analytic":
        r = cfg.rlgc()
        for k in RLGC_PRESET_KEYS:
            if r[k] != 0.0:
                knobs.append(dict(label=k, path=f"channel.{k}", nominal=r[k],
                                  source="config" if getattr(ch, k) is not None else "model", rel=0.2))
    if ch.xtalk == "coupled" and cfg.lanes.count > 1:
        st = cfg.stackup()
        for k in STACKUP_KEYS:
            knobs.append(dict(label=k, path=f"channel.{k}", nominal=st[k],
                              source="config" if getattr(ch, k) is not None else "model", rel=0.2))
        pitch, src = trace_pitch_um(cfg)
        knobs.append(dict(label="trace_pitch_um", path="channel.trace_pitch_um", nominal=pitch, source=src, rel=0.2))
    elif ch.xtalk == "fext" and cfg.lanes.count > 1:
        adj = cfg.xtalk_db()[0]
        knobs.append(dict(label="xtalk_adjacent_db", path="channel.xtalk_adjacent_db", nominal=adj,
                          source="config" if ch.xtalk_adjacent_db is not None else "model", rel=0.2))
    if cfg.rx.bw_hz is not None:
        # the receiver's bandwidth is the design's claim, and with the noise
        # at the input it moves both the pulse and the noise
        knobs.append(dict(label="rx_bw_hz", path="rx.bw_hz", nominal=cfg.rx.bw_hz, source="config", rel=0.2))
    return knobs


def sensitivity(cfg, eye_height_mv: float = 10.0, eye_width_ui: float = 0.05) -> dict:
    """Rerun the link with each knob at (1 - rel) and (1 + rel) of its nominal
    value; the eye-mask targets are moved by +-``eye_height_mv`` /
    +-``eye_width_ui`` without a rerun (the margins are read off the nominal
    result). Returns the nominal verdict and one row per knob."""
    from d2d_link.config import apply_overrides
    from d2d_link.engine import run_link
    from d2d_link.engine.statistical import resolved_targets

    def verdict(res):
        worst = res.worst
        return {"passes": bool(res.passes), "worst_lane": worst.lane, "margin": float(worst.margin),
                "eye_height_mv": 1e3 * res.eye_height_min_v, "eye_width_ui": res.eye_width_min_ui}

    base = run_link(cfg)
    nominal = verdict(base)
    rows = []
    for k in sensitivity_knobs(cfg):
        sides = {}
        for sign, name in ((-1.0, "low"), (1.0, "high")):
            value = k["nominal"] * (1.0 + sign * k["rel"])
            res = run_link(apply_overrides(cfg, {k["path"]: value}))
            sides[name] = {"value": value, **verdict(res)}
        rows.append({**k, **sides, "flips": sides["low"]["passes"] != nominal["passes"]
                     or sides["high"]["passes"] != nominal["passes"]})
    # the eye-mask targets: tighter / looser by a fixed step, read off the nominal eyes
    t = resolved_targets(cfg)
    eh, ew = 1e3 * base.eye_height_min_v, base.eye_width_min_ui
    for label, key, step, have in (("eye_height_mv", "eye_height_mv", eye_height_mv, eh),
                                   ("eye_width_ui", "eye_width_ui", eye_width_ui, ew)):
        nom, src = t[key]
        low, high = nom - step, nom + step
        ok_low, ok_high = base.lanes.link_up and have >= low, base.lanes.link_up and have >= high
        other_ok = all(r.log10_ber <= math.log10(r.target_ber) for r in base.stat) and (
            (ew >= t["eye_width_ui"][0]) if key == "eye_height_mv" else (eh >= t["eye_height_mv"][0]))
        rows.append(dict(label=f"target.{label}", path=f"target.{label}", nominal=nom, source=src, rel=None,
                         low={"value": low, "passes": bool(ok_low and other_ok), "worst_lane": base.worst.lane,
                              "margin": (have - low) / low if low > 0 else float("nan")},
                         high={"value": high, "passes": bool(ok_high and other_ok), "worst_lane": base.worst.lane,
                               "margin": (have - high) / high},
                         flips=bool((ok_low and other_ok) != nominal["passes"] or (ok_high and other_ok) != nominal["passes"])))
    return {"nominal": nominal, "rows": rows}


def sensitivity_markdown(sens: dict) -> str:
    n = sens["nominal"]
    lines = ["## Sensitivity", "",
             f"Nominal: {'PASS' if n['passes'] else 'FAIL'}, worst lane {n['worst_lane']} margin {n['margin']:+.3f} "
             f"(min eye {n['eye_height_mv']:.1f} mV / {n['eye_width_ui']:.3f} UI). Each estimate (source: model) and "
             "unverified number (source: survey) moved -20 % / +20 % (targets -/+ 10 mV, 0.05 UI); "
             "margin = min(eye height, eye width) relative to its target, worst lane.", "",
             "| parameter | source | nominal | low -> verdict (margin) | high -> verdict (margin) | flips |",
             "|---|---|---:|---|---|---|"]
    for r in sens["rows"]:
        lo, hi = r["low"], r["high"]
        lines.append(f"| {r['label']} | {r['source']} | {r['nominal']:.4g} | {lo['value']:.4g} -> "
                     f"{'PASS' if lo['passes'] else 'FAIL'} ({lo['margin']:+.3f}) | {hi['value']:.4g} -> "
                     f"{'PASS' if hi['passes'] else 'FAIL'} ({hi['margin']:+.3f}) | {'**yes**' if r['flips'] else 'no'} |")
    flips = [r["label"] for r in sens["rows"] if r["flips"]]
    lines += ["", ("Verdict-deciding: " + ", ".join(flips)) if flips else "No single perturbation flips the verdict.", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="Markdown file (default: stdout)")
    ap.add_argument("--json", type=Path, help="also write the report as JSON")
    ap.add_argument("--sensitivity", action="store_true",
                    help="also perturb every model / survey number by +-20 %% and report which flip the verdict")
    args = ap.parse_args(argv)
    from d2d_link.config import load_config

    cfg = load_config(args.config)
    rep = build(cfg)
    md = to_markdown(rep)
    if args.sensitivity:
        rep["sensitivity"] = sensitivity(cfg)
        md += "\n" + sensitivity_markdown(rep["sensitivity"])
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
