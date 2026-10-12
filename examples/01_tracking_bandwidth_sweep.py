"""Example 01: the residual jitter against the tracker bandwidth.

The forwarded clock cancels the PLL's phase noise; what it cannot cancel is
the jitter the two paths add separately (serializer, clock driver, receive
tree) and what the tree's delay and bandwidth let through. A per-lane phase
tracker follows the slow part of that difference. This sweeps its bandwidth
from none to infinite for the milestone link and prints the closed-form
residual beside a synthesised realisation at a few points, then does the
same with the PLL noise made partly uncorrelated (``clocking.correlation``)
to show the sum-of-independent-powers limit and the correlation-one zero.
Finally the statistical engine turns each bandwidth into an eye width.

Three checks the acceptance asks for are printed as numbers, not asserted
here (tests/test_forwarded_clock.py asserts them): correlation 1 with an
ideal tree leaves exactly zero; bandwidth -> infinity leaves zero; no
tracker leaves the two paths' independent powers added.
"""

import dataclasses
import math

import numpy as np

from _common import CONFIGS, OUT, plt_or_none
from d2d_link.clock.forwarded import ForwardedClock, residual_vs_track_bw
from d2d_link.config import load_config
from d2d_link.engine import run_statistical

cfg = load_config(CONFIGS / "standard_32g_x1.yaml")
ck = cfg.clocking
ideal_tree = dataclasses.replace(cfg, clocking=dataclasses.replace(ck, tree_delay_ps=0.0, tree_bw_hz=None,
                                                                   tree_rj_s=0.0))

print("correlation = 1, ideal tree, no path noise: residual "
      f"{1e15 * ForwardedClock(dataclasses.replace(ideal_tree, clocking=dataclasses.replace(ideal_tree.clocking, data_path_rj_s=0.0, clock_path_rj_s=0.0))).residual_sigma_s():.3f} fs"
      f"  (PLL itself {1e15 * ForwardedClock(cfg).pll_rms_s():.1f} fs in band)")
indep = math.hypot(ck.data_path_rj_s, ck.clock_path_rj_s)
print(f"no tracker, ideal tree: residual {1e15 * ForwardedClock(dataclasses.replace(ideal_tree, clocking=dataclasses.replace(ideal_tree.clocking, track_bw_hz=None))).residual_sigma_s():.2f} fs"
      f" = sqrt({1e15 * ck.data_path_rj_s:.0f}^2 + {1e15 * ck.clock_path_rj_s:.0f}^2) = {1e15 * indep:.2f} fs")

bws = [None, 1e5, 3e5, 1e6, 3e6, 1e7, 3e7, 1e8, 3e8, 1e9, 3e9, 1e10, math.inf]
labels = ["none"] + [f"{b:.0e}" for b in bws[1:-1]] + ["inf"]
rows = []
print(f"\n{'tracker bw [Hz]':>16s} {'closed form [fs]':>17s} {'synth [fs]':>11s} {'eye width [UI]':>15s} {'eye height [mV]':>16s}")
for bw, lab in zip(bws, labels):
    c = dataclasses.replace(cfg, clocking=dataclasses.replace(ck, track_bw_hz=bw))
    fc = ForwardedClock(c)
    sig = fc.residual_sigma_s()
    synth = float(np.std(fc.synthesize(1 << 18, np.random.default_rng(1))[0])) if lab in ("none", "1e+06", "1e+08", "inf") else float("nan")
    s = run_statistical(c)
    rows.append((lab, sig, s.eye_width_ui, s.eye_height_v))
    print(f"{lab:>16s} {1e15 * sig:17.2f} {'' if np.isnan(synth) else f'{1e15 * synth:.2f}':>11s} "
          f"{s.eye_width_ui:15.3f} {1e3 * s.eye_height_v:16.1f}")

print("\ncorrelation sweep at the configured 2 MHz tracker (ideal tree, same path noise):")
print(f"{'correlation':>12s} {'residual [fs]':>14s} {'of which PLL leak [fs]':>23s}")
for rho in (1.0, 0.99, 0.9, 0.5, 0.0):
    c = dataclasses.replace(ideal_tree, clocking=dataclasses.replace(ideal_tree.clocking, correlation=rho))
    b = ForwardedClock(c).budget()
    print(f"{rho:12.2f} {1e15 * b.total_s:14.2f} {1e15 * b.common_leak_s:23.2f}")

curve_bw = np.logspace(4, 10.5, 60)
curve = residual_vs_track_bw(cfg, curve_bw)
curve_rho0 = residual_vs_track_bw(dataclasses.replace(cfg, clocking=dataclasses.replace(ck, correlation=0.0)), curve_bw)
print(f"\nhalf-way point: the residual drops to half its untracked value at a tracker bandwidth of "
      f"{curve_bw[int(np.argmin(np.abs(curve - 0.5 * curve[0])))]:.2e} Hz")

plt = plt_or_none()
if plt is not None:
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.semilogx(curve_bw, 1e15 * curve, label="correlation 1 (shared PLL)")
    ax.semilogx(curve_bw, 1e15 * curve_rho0, label="correlation 0 (independent PLLs)")
    ax.axhline(1e15 * indep, color="gray", ls=":", lw=0.8, label="independent path noise, power sum")
    ax.set_xlabel("tracker bandwidth [Hz]")
    ax.set_ylabel("residual jitter at the sampler [fs RMS]")
    ax.set_title("forwarded clock: residual vs tracking bandwidth")
    ax.grid(alpha=0.3, which="both")
    ax.legend()
    fig.tight_layout()
    path = OUT / "01_tracking_bandwidth_sweep.png"
    fig.savefig(path, dpi=120)
    print(f"wrote {path}")
