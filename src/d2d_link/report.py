"""The timing budget of a link as a structured report: ``report`` (dict),
``to_markdown``, and ``sensitivity`` / ``sensitivity_markdown`` ("which
guesses decide the verdict": every model preset and survey number the config
leans on moved by +-20 %, the link rerun, the verdict-flipping ones marked).

``tools/budget_report.py`` is the command line over these; the GUI renders
the same dicts (invariant #1: nothing here simulates, it reads ``LinkResult``
and the clock's closed-form budget). Everything carries its source
(invariant #5).
"""

from __future__ import annotations

import math


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
            ("QDR edge sampling: clock noise folded from fs/2 - f", b.edge_alias_s),
            ("phase-interpolator quantisation (uniform)", clock.quantisation_sigma_s())]
    return rows


def _xtalk_level(cfg, res) -> dict:
    """The nearest neighbour's coupling at Nyquist and where it came from:
    the file's own term for ``xtalk: touchstone`` (the lanes carry it in their
    extras; the first lane whose file has a neighbour speaks), the configured
    or preset level otherwise. None when crosstalk is off."""
    if cfg.channel.xtalk == "none":
        return {"adjacent_db": None, "adjacent_source": None}
    if cfg.channel.xtalk == "touchstone":
        levels = [r.extras.get("xtalk_adjacent_db") for r in res.stat if r.extras.get("xtalk_adjacent_db") is not None]
        return {"adjacent_db": max(levels) if levels else None, "adjacent_source": "file"}
    return {"adjacent_db": cfg.xtalk_db()[0],
            "adjacent_source": "config" if cfg.channel.xtalk_adjacent_db is not None else "model"}


def report(cfg, res, clock) -> dict:
    from d2d_link.channel.coupled import describe

    ui = cfg.ui
    rows = budget_rows(cfg, clock)
    total = math.sqrt(sum(v ** 2 for _, v in rows))
    from d2d_link.engine.statistical import target_keys

    lm = res.lanes
    t = res.targets
    keys = target_keys(cfg)
    out = {
        "link": {"data_rate_gtps": cfg.data_rate_gtps, "package": cfg.package.kind,
                 "length_mm": cfg.channel.length_mm, "ui_ps": ui * 1e12,
                 "forwarded_clock_ghz": cfg.forwarded_clock_hz / 1e9,
                 "lanes_requested": lm.requested_width, "lanes_active": lm.active_width,
                 "repair": lm.mode, "failed": list(lm.failed), "unrepaired": list(lm.unrepaired),
                 "insertion_loss_nyquist_db": res.stat[0].extras["insertion_loss_nyquist_db"] if res.stat else None,
                 "grid_top_ghz": cfg.sim.osr * cfg.f_nyquist / 1e9,
                 "grid_top_response": res.stat[0].extras.get("grid_top_response") if res.stat else None,
                 "tx_pll_rms_fs": 1e15 * clock.pll_rms_s(),
                 "local_pll_rms_fs": 1e15 * clock.local_pll_rms_s(),
                 "local_pll_fn_hz": cfg.clocking.local_pll_fn_hz, "local_pll_bw_3db_hz": clock.local_pll_bw_3db_hz(),
                 "spur_terms": [{"f_hz": f0, "amplitude_fs": 1e15 * a} for f0, a in clock.spur_terms()],
                 "verdict": "PASS" if res.passes else "FAIL"},
        "jitter_budget": [{"term": name, "fs": 1e15 * v, "ui": v / ui} for name, v in rows]
                         + [{"term": "total (power sum)", "fs": 1e15 * total, "ui": total / ui}],
        "targets": {k: {"value": v, "source": src, "key": keys[k]} for k, (v, src) in t.items()},
        "crosstalk": ({"mode": cfg.channel.xtalk, **describe(cfg)} if cfg.channel.xtalk == "coupled"
                      else {"mode": cfg.channel.xtalk, **_xtalk_level(cfg, res)}),
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
    lines += ["", "## Targets", "", "| quantity | value | source | table key |", "|---|---:|---|---|"]
    for k, v in rep["targets"].items():
        lines.append(f"| {k} | {v['value']:g} | {v['source']} | {v.get('key', '')} |")
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
    ``label, path, nominal, source`` and either ``rel`` (moved by +-rel of the
    nominal) or ``step`` (moved by +-step: dB levels and profile shifts, where
    +-20 % of -30 dB would be +-6 dB, a factor 2 in amplitude). A parameter
    the config sets explicitly is its own claim (source config) and still
    listed: since 0.13.3 that includes the clock path's white and wander
    jitter, which decide the x16 module (example 11), and the PLL profiles'
    level (``pll_shift_db``, +-3 dB: a borrowed bench profile, source model)."""
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
    if ch.xtalk == "coupled" and cfg.lanes.count + cfg.lanes.spare_count > 1:
        st = cfg.stackup()
        for k in STACKUP_KEYS:
            knobs.append(dict(label=k, path=f"channel.{k}", nominal=st[k],
                              source="config" if getattr(ch, k) is not None else "model", rel=0.2))
        pitch, src = trace_pitch_um(cfg)
        knobs.append(dict(label="trace_pitch_um", path="channel.trace_pitch_um", nominal=pitch, source=src, rel=0.2))
    elif ch.xtalk == "fext" and cfg.lanes.count + cfg.lanes.spare_count > 1:
        adj, sec = cfg.xtalk_db()
        # the second neighbour is pinned while the nearest one moves (it defaults
        # to nearest - 12 dB and would otherwise move with it, fourth health check)
        knobs.append(dict(label="xtalk_adjacent_db", path="channel.xtalk_adjacent_db", nominal=adj,
                          source="config" if ch.xtalk_adjacent_db is not None else "model", step=3.0,
                          pin={"channel.xtalk_second_db": sec}))
        knobs.append(dict(label="xtalk_second_db", path="channel.xtalk_second_db", nominal=sec,
                          source="config" if ch.xtalk_second_db is not None else "model", step=3.0))
    if ch.xtalk_next == "fixed":
        knobs.append(dict(label="next_db", path="channel.next_db", nominal=ch.next_db, source="config", step=3.0))
    ck = cfg.clocking
    from dataclasses import replace

    from d2d_link.clock.forwarded import ForwardedClock

    total = ForwardedClock(cfg).budget().total_s
    for name in ("data_path_rj_s", "clock_path_rj_s", "tree_rj_s", "data_path_wander_s", "clock_path_wander_s", "pll_rj_s",
                 "local_pll_rj_s"):
        v = getattr(ck, name, 0.0)
        if not v:
            continue
        # a jitter the clocking filters away (the clock path's white jitter behind a
        # 1 MHz local PLL moves the total 331.54 -> 331.55 fs) is not run: two full
        # links for nothing (fourth health check)
        moved = ForwardedClock(replace(cfg, clocking=replace(ck, **{name: 1.2 * v}))).budget().total_s - total
        if abs(moved) < 0.1e-15:
            continue
        knobs.append(dict(label=name, path=f"clocking.{name}", nominal=v, source="config", rel=0.2))
    if ck.pll_profile is not None:
        knobs.append(dict(label="pll_shift_db", path="clocking.pll_shift_db", nominal=ck.pll_shift_db,
                          source="config" if ck.pll_shift_db != 0.0 else "model", step=3.0))
    if ck.local_pll_profile is not None:
        knobs.append(dict(label="local_pll_shift_db", path="clocking.local_pll_shift_db", nominal=ck.local_pll_shift_db,
                          source="config" if ck.local_pll_shift_db != 0.0 else "model", step=3.0))
    if cfg.rx.bw_hz is not None:
        # the receiver's bandwidth is the design's claim, and with the noise
        # at the input it moves both the pulse and the noise
        knobs.append(dict(label="rx_bw_hz", path="rx.bw_hz", nominal=cfg.rx.bw_hz, source="config", rel=0.2))
    else:
        # a flat front end is an idealisation every bundled pass rests on (ROADMAP
        # P2 #2): one design side, a first-order pole at 2 f_N (the data rate in
        # GHz), with the noise left at the sampler; the other side is the flat
        # nominal itself (0.15.2)
        knobs.append(dict(label="rx_bw_hz (flat)", path="rx.bw_hz", nominal=math.inf, source="model",
                          sides={"low": 2.0 * cfg.f_nyquist, "high": math.inf}))
    return knobs


def sensitivity(cfg, eye_height_mv: float = 10.0, eye_width_ui: float = 0.05, progress=None) -> dict:
    """Rerun the link with each knob at (1 - rel) and (1 + rel) of its nominal
    value; the eye-mask targets are moved by +-``eye_height_mv`` /
    +-``eye_width_ui`` without a rerun (the margins are read off the nominal
    result). Returns the nominal verdict and one row per knob. ``progress``
    (done, total) is called after each run (the GUI's queue reads it)."""
    from d2d_link.config import apply_overrides
    from d2d_link.engine import run_link
    from d2d_link.engine.statistical import resolved_targets

    def verdict(res):
        worst = res.worst
        return {"passes": bool(res.passes), "worst_lane": worst.lane, "margin": float(worst.margin),
                "eye_height_mv": 1e3 * res.eye_height_min_v, "eye_width_ui": res.eye_width_min_ui}

    knobs = sensitivity_knobs(cfg)
    total, done = 1 + 2 * len(knobs), 0

    def tick():
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total)

    base = run_link(cfg)
    tick()
    nominal = verdict(base)
    rows = []
    for k in knobs:
        sides = {}
        for sign, name in ((-1.0, "low"), (1.0, "high")):
            if "sides" in k:
                value = k["sides"][name]
                if value == k["nominal"]:               # a side that is the nominal design: no rerun
                    tick()
                    sides[name] = {"value": value, **nominal}
                    continue
            else:
                value = k["nominal"] + sign * k["step"] if "step" in k else k["nominal"] * (1.0 + sign * k["rel"])
            try:
                c = apply_overrides(cfg, {**k.get("pin", {}), k["path"]: value})
            except ValueError as exc:
                # a side the config refuses (a -2 dB crosstalk level moved to +1 dB)
                # is reported, not fatal: before 0.13.10 it aborted the whole run
                tick()
                sides[name] = {"value": value, "passes": None, "worst_lane": None, "margin": float("nan"),
                               "skipped": str(exc)}
                continue
            res = run_link(c)
            tick()
            sides[name] = {"value": value, **verdict(res)}
        rows.append({**k, **sides, "flips": any(sides[s]["passes"] is not None and sides[s]["passes"] != nominal["passes"]
                                                for s in ("low", "high"))})
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
        other = (ew - t["eye_width_ui"][0]) / t["eye_width_ui"][0] if key == "eye_height_mv" else \
            (eh - t["eye_height_mv"][0]) / t["eye_height_mv"][0]
        rows.append(dict(label=f"target.{label}", path=f"target.{label}", nominal=nom, source=src, rel=None,
                         low={"value": low, "passes": bool(ok_low and other_ok), "worst_lane": base.worst.lane,
                              "margin": min((have - low) / low, other) if low > 0 else float("nan")},
                         high={"value": high, "passes": bool(ok_high and other_ok), "worst_lane": base.worst.lane,
                               "margin": min((have - high) / high, other)},
                         flips=bool((ok_low and other_ok) != nominal["passes"] or (ok_high and other_ok) != nominal["passes"])))
    return {"nominal": nominal, "rows": rows}


def sensitivity_markdown(sens: dict) -> str:
    n = sens["nominal"]
    lines = ["## Sensitivity", "",
             f"Nominal: {'PASS' if n['passes'] else 'FAIL'}, worst lane {n['worst_lane']} margin {n['margin']:+.3f} "
             f"(min eye {n['eye_height_mv']:.1f} mV / {n['eye_width_ui']:.3f} UI). Each estimate (source: model) and "
             "unverified number (source: survey), and each jitter the config claims, moved -20 % / +20 % (dB levels and "
             "profile shifts -/+ 3 dB; targets -/+ 10 mV, 0.05 UI); "
             "margin = min(eye height, eye width) relative to its target, worst lane.", "",
             "| parameter | source | nominal | low -> verdict (margin) | high -> verdict (margin) | flips |",
             "|---|---|---:|---|---|---|"]
    for r in sens["rows"]:
        lo, hi = r["low"], r["high"]
        def side(s):
            if s["passes"] is None:
                return f"{s['value']:.4g} -> n/a (refused by the config)"
            return f"{s['value']:.4g} -> {'PASS' if s['passes'] else 'FAIL'} ({s['margin']:+.3f})"
        lines.append(f"| {r['label']} | {r['source']} | {r['nominal']:.4g} | {side(lo)} | {side(hi)} | "
                     f"{'**yes**' if r['flips'] else 'no'} |")
    flips = [r["label"] for r in sens["rows"] if r["flips"]]
    lines += ["", ("Verdict-deciding: " + ", ".join(flips)) if flips else "No single perturbation flips the verdict.", ""]
    return "\n".join(lines)


# ------------------------------------------------------------ eye-width attribution
#
# Since 0.13.6 every bundled 32 GT/s config fails on eye width. Where does the
# width go? Each cause is switched off by a replace of the config; the
# remainder with all of them off is the channel's ISI and the receiver noise.
# The causes interact (edge crosstalk costs more once jitter has pushed the
# bathtub's walls in), so the split is the Shapley value: each cause's gain
# averaged over every order of switching them off, which sums exactly to the
# gap (0.13.8).

ATTRIBUTION_CAUSES = ("crosstalk", "jitter", "PI step")


def attribution_causes(cfg) -> tuple[str, ...]:
    """The causes this config has: crosstalk (lanes > 1 and any xtalk mode),
    jitter (always), the PI step (``LinkConfig.pi_step_ui`` > 0)."""
    out = []
    if (cfg.channel.xtalk != "none" or cfg.channel.xtalk_next != "none") and cfg.lanes.count + cfg.lanes.spare_count > 1:
        out.append("crosstalk")
    out.append("jitter")
    if cfg.pi_step_ui > 0.0:
        out.append("PI step")
    return tuple(out)


def switched_off(cfg, off):
    """``cfg`` with the named causes removed: crosstalk -> ``xtalk`` and
    ``xtalk_next`` none; jitter -> every clock-path term zero (both PLL
    profiles and white parts, path white and wander, tree jitter, DCD and the
    QDR I/Q skew (0.15.5; until then a 0.06 UI skew stayed in the "ideal"
    eye, sixth health check); the tree's delay and the tracker stay, with
    nothing to track they cost nothing); PI step -> ``clocking.pi_step_ui`` 0 and an ideal deskew."""
    import dataclasses

    R = dataclasses.replace
    ch, ck, ln = cfg.channel, cfg.clocking, cfg.lanes
    if "crosstalk" in off:
        ch = R(ch, xtalk="none", xtalk_next="none")
    if "jitter" in off:
        ck = R(ck, pll_profile=None, pll_rj_s=0.0, local_pll_profile=None, local_pll_rj_s=0.0, data_path_rj_s=0.0,
               clock_path_rj_s=0.0, tree_rj_s=0.0, data_path_wander_s=0.0, clock_path_wander_s=0.0, dcd_ui=0.0,
               tx_dcd_ui=0.0, qdr_quadrature_ui=0.0)
    if "PI step" in off:
        ck = R(ck, pi_step_ui=0.0)
        ln = R(ln, deskew_with_tracker="ideal")
    return R(cfg, channel=ch, clocking=ck, lanes=ln)


def shapley(items, value) -> dict:
    """Each item's gain ``value(S | {i}) - value(S)`` averaged over every
    order of adding the items; the gains sum to ``value(all) - value(none)``."""
    import itertools

    n = len(items)
    out = {}
    for i in items:
        rest = [j for j in items if j != i]
        total = 0.0
        for k in range(n):
            for S in itertools.combinations(rest, k):
                w = math.factorial(k) * math.factorial(n - k - 1) / math.factorial(n)
                total += w * (value(frozenset(S) | {i}) - value(frozenset(S)))
        out[i] = total
    return out


def attribution(cfg, progress=None) -> dict:
    """The worst-lane eye width with every subset of the config's causes
    switched off (2^k runs, k <= 3), and each cause's Shapley share of the
    gap between the full eye and the ISI-and-noise eye."""
    import itertools

    from d2d_link.engine import run_link

    items = attribution_causes(cfg)
    eye, lane, target = {}, {}, None
    subsets = [frozenset(S) for k in range(len(items) + 1) for S in itertools.combinations(items, k)]
    for done, S in enumerate(subsets, 1):
        res = run_link(switched_off(cfg, S))
        eye[S], lane[S] = res.eye_width_min_ui, res.worst.lane
        target = res.worst.targets["eye_width_ui"][0]
        if progress is not None:
            progress(done, len(subsets))
    share = shapley(items, lambda S: eye[S])
    full, ideal = eye[frozenset()], eye[frozenset(items)]
    return {"causes": list(items), "target_ui": target, "full_ui": full, "ideal_ui": ideal,
            "worst_lane": lane[frozenset()], "ideal_lane": lane[frozenset(items)],
            "share_ui": share, "alone_off_ui": {i: eye[frozenset({i})] for i in items},
            "subsets": [{"off": sorted(S), "eye_width_ui": eye[S], "worst_lane": lane[S]} for S in subsets]}


def attribution_markdown(att: dict) -> str:
    gap = att["ideal_ui"] - att["full_ui"]
    t = att["target_ui"]
    lines = ["## Where the eye width goes", "",
             f"Worst-lane eye width {att['full_ui']:.4f} UI (lane {att['worst_lane']}); with every cause below switched "
             f"off (ISI and noise only) {att['ideal_ui']:.4f} UI; gap {gap:.4f} UI; target {t:g} UI. Shares are "
             "Shapley values (averaged over every order of switching the causes off) and sum to the gap.", "",
             "| cause | share [UI] | of gap | eye with only this off [UI] | passes |", "|---|---:|---:|---:|---|"]
    for i in att["causes"]:
        a = att["alone_off_ui"][i]
        lines.append(f"| {i} | {att['share_ui'][i]:.4f} | {att['share_ui'][i] / gap if gap > 0 else 0.0:.0%} | "
                     f"{a:.4f} | {'yes' if a >= t else 'no'} |")
    lines.append("")
    return "\n".join(lines)


__all__ = ["budget_rows", "report", "to_markdown", "build", "sensitivity_knobs", "sensitivity",
           "attribution", "attribution_causes", "attribution_markdown", "switched_off", "shapley",
           "sensitivity_markdown"]
