"""Example 13: which guesses decide each bundled config's verdict.

``tools/budget_report.py --sensitivity`` (``report.sensitivity``) moves every
number a config's verdict leans on and is not a specification value -- the
``source: model`` presets (trace loss, Z0, stack-up, behavioural crosstalk),
the ``source: survey`` numbers (bump pitch, the eye-mask targets) and the
clock-path jitters the config claims -- by +-20 % (dB levels and the PLL
profiles' level by +-3 dB; the targets by +-10 mV / +-0.05 UI), reruns the
link, and reads the worst lane's margin: min(eye height, eye width) over
its target, relative to it.

Until 0.14.1 those margins were in ROADMAP P1 #1 and cairn/spec-sources.md
only as numbers someone had typed from a hand run (fourth health check:
nothing produced them). This example prints them, so the accept gate of
``tools/example_drift.py`` flags a doc that still quotes an old one.

For each config: the nominal verdict and margin, every knob's two sides,
the sides that flip the verdict, and the three that come closest without
flipping it (smallest |margin|).
"""

import os
from concurrent.futures import ProcessPoolExecutor

from _common import CONFIGS
from d2d_link.config import load_config
from d2d_link.report import sensitivity

NAMES = ("standard_32g_x1", "standard_32g_x16_module", "standard_32g_x16_repair", "advanced_32g_x64_spare",
         "standard_32g_x5_coupled")


def run(name):
    return name, sensitivity(load_config(CONFIGS / f"{name}.yaml"))


def fmt(side):
    if side["passes"] is None:
        return "n/a"
    return f"{'PASS' if side['passes'] else 'FAIL'} {side['margin']:+.3f}"


def value(v):
    return f"{v:.4g}" if isinstance(v, float) else str(v)


if __name__ == "__main__":
    with ProcessPoolExecutor(max_workers=max(1, min(len(NAMES), os.cpu_count() or 1))) as pool:
        results = dict(pool.map(run, NAMES))
    summary = []
    for name in NAMES:
        s = results[name]
        n = s["nominal"]
        ok = n["passes"]
        print(f"\n{name}: nominal {'PASS' if ok else 'FAIL'}, worst lane {n['worst_lane']} margin {n['margin']:+.3f} "
              f"(smallest eye over the lanes {n['eye_height_mv']:.1f} mV / {n['eye_width_ui']:.3f} UI)")
        print(f"  {'parameter':<22s} {'source':>7s} {'nominal':>9s} {'low':>9s} -> {'verdict':<12s} {'high':>9s} -> {'verdict':<12s} flips")
        sides = []
        for r in s["rows"]:
            lo, hi = r["low"], r["high"]
            print(f"  {r['label']:<22s} {r['source']:>7s} {value(r['nominal']):>9s} {value(lo['value']):>9s} -> {fmt(lo):<12s} "
                  f"{value(hi['value']):>9s} -> {fmt(hi):<12s} {'yes' if r['flips'] else ''}".rstrip())
            for tag, side in (("low", lo), ("high", hi)):
                if side["passes"] is not None:
                    sides.append((side["margin"], f"{r['label']} {tag} {value(side['value'])}", side["passes"] != ok))
        flipped = sorted((t for t in sides if t[2]), key=lambda t: abs(t[0]))
        held = sorted((t for t in sides if not t[2]), key=lambda t: abs(t[0]))
        flips = [r["label"] for r in s["rows"] if r["flips"]]
        if flipped:
            print("  flipped by: " + ", ".join(f"{label} {m:+.3f}" for m, label, _ in flipped))
        print("  closest to flipping: " + ", ".join(f"{label} {m:+.3f}" for m, label, _ in held[:3]))
        summary.append((name, ok, n["margin"], flips))
    print("\nsummary (+-20 %, dB +-3 dB, targets +-10 mV / +-0.05 UI):")
    for name, ok, m, flips in summary:
        print(f"  {name:<26s} {'PASS' if ok else 'FAIL'} {m:+.3f}  flipped by: {', '.join(flips) if flips else 'nothing'}")
