"""Example 14: what the x16 repair module's thin margin rests on.

Example 13 found the most fragile pass among the bundled configs:
``configs/standard_32g_x16_repair.yaml`` (x16, physical lane 5 dead, the
module degraded to its intact x8 half) passes the 0.65 UI target with a
relative margin of +0.028. It fails if the borrowed Tx PLL profile is 3 dB
worse, and it is left with +0.005 if the data path's white jitter is 20 %
higher. The x16 module, which has the same channel class, survives both.

Two things set the repair module apart from the x16 module:

- **no local PLL.** The forwarded clock goes straight through the 30 ps,
  20 GHz tree to the per-lane tracker. Near fs/2 the tree turns the Tx PLL's
  floor around instead of cancelling it (example 10), so the PLL's level
  reaches the sampler. The x16 module re-times the clock with a 1 MHz local
  PLL and does not see that leak.
- **a coarse phase interpolator.** The config declares a 1/16 UI deskew step
  (1.95 ps), and under a tracker that is the PI step (0.13.0). The x16 module
  uses 1/64 UI. Example 12 puts the PI step at 23 % of this config's
  eye-width gap.

This example takes the design levers one at a time. For each it gives the
closed-form residual, the worst lane's margin at the nominal PLL and at
+3 dB, and the PLL shift the module withstands before it fails. The last
number is bisected to 0.1 dB on full module runs. Every point is a
dataclass replace of the repair config; no model changes.
"""

import dataclasses

from _common import CONFIGS
from d2d_link.clock.forwarded import ForwardedClock
from d2d_link.config import load_config
from d2d_link.engine import run_link
from d2d_link.engine.statistical import resolved_targets

R = dataclasses.replace
rep = load_config(CONFIGS / "standard_32g_x16_repair.yaml")
ck0 = rep.clocking


def clocked(cfg, **kw):
    return R(cfg, clocking=R(cfg.clocking, **kw))


def margin(cfg, shift_db=0.0):
    res = run_link(clocked(cfg, pll_shift_db=cfg.clocking.pll_shift_db + shift_db))
    return res.passes, res.worst.margin, res.worst.eye_width_ui, res.worst.lane


def withstands(cfg, hi=12.0, tol=0.1):
    """The largest Tx PLL shift [dB] the module still passes at (bisection)."""
    if not margin(cfg)[0]:
        return float("nan")
    if margin(cfg, hi)[0]:
        return float("inf")
    lo = 0.0
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if margin(cfg, mid)[0] else (lo, mid)
    return lo


# --------------------------------------------------- 1. where the residual comes from
b = ForwardedClock(rep).budget()
terms = (("Tx PLL leak through the tree", b.common_leak_s), ("data path white", b.data_path_s),
         ("data path wander", b.data_wander_s), ("clock path white", b.clock_path_s),
         ("clock path wander", b.clock_wander_s), ("tree", b.tree_s))
print(f"x16 repair: {rep.lanes.count} lanes, failed {list(rep.lanes.failed)} -> {rep.lanes.repair}; "
      f"tree {ck0.tree_delay_ps:g} ps / {ck0.tree_bw_hz / 1e9:g} GHz, tracker {ck0.track_bw_hz / 1e6:g} MHz, "
      f"no local PLL, PI step {rep.pi_step_ui:.4f} UI ({1e12 * rep.pi_step_ui * rep.ui:.2f} ps)")
print(f"  residual (closed form) {1e15 * b.gaussian_s:.1f} fs RMS:")
for name, s in terms:
    print(f"    {name:<30s} {1e15 * s:7.1f} fs  ({100 * (s / b.gaussian_s) ** 2:4.1f} % of the power)")
step = rep.pi_step_ui * rep.ui
print(f"  and the PI step: a bounded box of {1e12 * step:.2f} ps (RMS {1e15 * step / 12 ** 0.5:.0f} fs, but at the target BER a box costs "
      f"about its width, not 14 sigma of its RMS)")

# --------------------------------------------------- 2. levers one at a time
x16 = load_config(CONFIGS / "standard_32g_x16_module.yaml")
levers = [
    ("bundled", rep),
    ("PI step 1/32 UI", clocked(rep, pi_step_ui=1 / 32)),
    ("PI step 1/64 UI (as x16)", clocked(rep, pi_step_ui=1 / 64)),
    ("data path white 150 fs", clocked(rep, data_path_rj_s=150e-15)),
    ("data path white 100 fs", clocked(rep, data_path_rj_s=100e-15)),
    ("clock path white 100 fs", clocked(rep, clock_path_rj_s=100e-15)),
    ("tree 15 ps", clocked(rep, tree_delay_ps=15.0)),
    ("tree 0 ps", clocked(rep, tree_delay_ps=0.0)),
    ("tracker 5 MHz", clocked(rep, track_bw_hz=5e6)),
    ("local PLL as x16", clocked(rep, local_pll_profile=x16.clocking.local_pll_profile,
                                 local_pll_fn_hz=x16.clocking.local_pll_fn_hz)),
]
target = resolved_targets(rep)["eye_width_ui"]
print(f"\nlevers one at a time (worst-lane margin = eye width over the {target[0]:g} UI target, source: {target[1]}, relative):")
print(f"  {'lever':<26s} {'residual [fs]':>13s} {'margin':>8s} {'eye [UI]':>9s} {'at +3 dB':>9s} {'withstands':>11s}")
rows = []
for name, cfg in levers:
    s = ForwardedClock(cfg).budget().gaussian_s
    ok, m, ew, _ = margin(cfg)
    ok3, m3, _, _ = margin(cfg, 3.0)
    w = withstands(cfg)
    rows.append((name, s, m, m3, w))
    ws = "> 12 dB" if w == float("inf") else ("fails" if w != w else f"+{w:.1f} dB")
    print(f"  {name:<26s} {1e15 * s:13.1f} {m:+8.3f} {ew:9.4f} {m3:+9.3f} {ws:>11s}")

base_w = rows[0][4]
best = max(rows[1:], key=lambda r: r[4])
print(f"\n  bundled: the module withstands +{base_w:.1f} dB of Tx PLL level; the strongest single lever is "
      f"'{best[0]}' ({'> 12 dB' if best[4] == float('inf') else f'+{best[4]:.1f} dB'})")
three = [r[0] for r in rows[1:] if r[3] >= 0.0]
print(f"  levers that keep it passing at +3 dB: {', '.join(three) if three else 'none'}")
