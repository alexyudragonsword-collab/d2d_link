"""Example 04: the receiver's local PLL, locked to the forwarded clock.

Milestone 1 had the sampler clocked straight off the forwarded clock. A real
receiver puts a PLL on it (to multiply, to clean, to drive its tree), and
that PLL's loop bandwidth is the tracking bandwidth that matters: below it
the forwarded phase -- and with it the transmit PLL's noise, which the data
carries too -- passes to the sampler and cancels; above it the receiver runs
on its own oscillator's noise. Both clocks come from pll_simulator profiles:
the transmit side is the milestone link's SSPLL (Markulic 2016), the local
PLL the fractional SPLL anchor (Wu 2019).

Three things the acceptance asks for, printed as numbers (asserted in
tests/test_local_pll.py): loop bandwidth -> 0 leaves the two PLLs' powers
added (two independent clocks); -> infinity leaves zero even though the
local PLL is noisy; in between the Tx leak falls *and the local noise falls
with it* -- in a forwarded-clock link a wider loop is better for both, unlike
an independent-clock receiver where the two trade. What does trade against
the loop bandwidth is the noise that enters the clock path before the PLL
(driver jitter, wander): the loop filters it, so a narrow loop keeps it out
while a wide loop lets it through. The second part isolates that with a
white clock-path jitter and finds the optimum; the module's own sweep in
the first part shows the same through its clock-path wander. The third part
puts a latency and a phase-interpolator step on the per-lane tracker.
"""

import dataclasses
import math

import numpy as np

from _common import CONFIGS, OUT, plt_or_none
from d2d_link.clock.forwarded import ForwardedClock, residual_vs_local_pll_bw
from d2d_link.config import load_config
from d2d_link.engine import run_statistical

cfg = load_config(CONFIGS / "standard_32g_x16_module.yaml")
# one lane, the module's clocking, no crosstalk: the clock path alone
base = dataclasses.replace(cfg, lanes=dataclasses.replace(cfg.lanes, count=1, failed=(), repair="none",
                                                          skew_sigma_ps=0.0),
                           channel=dataclasses.replace(cfg.channel, xtalk="none"))
ck = base.clocking
fc = ForwardedClock(base)
print(f"Tx PLL {ck.pll_profile.split('/')[-1]}: {1e15 * fc.pll_rms_s():.1f} fs in band; "
      f"local PLL {ck.local_pll_profile.split('/')[-1]}: {1e15 * fc.local_pll_rms_s():.1f} fs; "
      f"loop natural frequency {ck.local_pll_fn_hz / 1e6:g} MHz (-3 dB {fc.local_pll_bw_3db_hz() / 1e6:.2f} MHz), "
      f"damping {ck.local_pll_damping:g}")

ideal = dataclasses.replace(ck, tree_delay_ps=0.0, tree_bw_hz=None, tree_rj_s=0.0, data_path_rj_s=0.0,
                            clock_path_rj_s=0.0, data_path_wander_s=0.0, clock_path_wander_s=0.0,
                            track_bw_hz=None, pi_step_ui=0.0)
lo = ForwardedClock(dataclasses.replace(base, clocking=dataclasses.replace(ideal, local_pll_fn_hz=1e3))).budget()
hi = ForwardedClock(dataclasses.replace(base, clocking=dataclasses.replace(ideal, local_pll_fn_hz=1e13))).budget()
print(f"loop -> 0 (1 kHz), ideal tree, no path noise: residual {1e15 * lo.total_s:.1f} fs "
      f"= sqrt({1e15 * fc.pll_rms_s():.1f}^2 + {1e15 * fc.local_pll_rms_s():.1f}^2 + spurs {1e15 * lo.spur_s:.1f}^2) "
      f"= {1e15 * math.sqrt(fc.pll_rms_s() ** 2 + fc.local_pll_rms_s() ** 2 + lo.spur_s ** 2):.1f} fs "
      f"(two independent clocks; the local PLL's spurs pass a loop this narrow)")
print(f"loop -> inf (10 THz): residual {1e15 * hi.total_s:.3f} fs")

bws = [1e4, 3e4, 1e5, 3e5, 1e6, 3e6, 1e7, 3e7, 1e8, 3e8, 1e9]
print(f"\nloop bandwidth sweep, the module's clock path (tree, path noise, wander, 2 MHz tracker with "
      f"{ck.track_delay_ui} UI latency and {ck.pi_step_ui:g} UI steps):")
print(f"{'loop bw [Hz]':>12s} {'Tx leak [fs]':>13s} {'local [fs]':>11s} {'wander [fs]':>12s} {'total [fs]':>11s} "
      f"{'eye width [UI]':>15s} {'eye height [mV]':>16s}")
rows = []
for bw, b in zip(bws, residual_vs_local_pll_bw(base, bws)):
    c = dataclasses.replace(base, clocking=dataclasses.replace(ck, local_pll_fn_hz=bw))
    s = run_statistical(c)
    wander = math.hypot(b.data_wander_s, b.clock_wander_s)
    rows.append((bw, b, s))
    print(f"{bw:12.0e} {1e15 * b.common_leak_s:13.1f} {1e15 * b.local_pll_s:11.1f} {1e15 * wander:12.1f} "
          f"{1e15 * b.total_s:11.1f} {s.eye_width_ui:15.3f} {1e3 * s.eye_height_v:16.1f}")

print("\nthe trade-off: 300 fs of white jitter on the clock path before the local PLL, ideal tree, no wander:")
cp = dataclasses.replace(ideal, clock_path_rj_s=300e-15)
sw = [(bw, ForwardedClock(dataclasses.replace(base, clocking=dataclasses.replace(cp, local_pll_fn_hz=bw))).budget())
      for bw in np.logspace(4, 10, 31)]
best = min(sw, key=lambda t: t[1].total_s)
print(f"{'loop bw [Hz]':>12s} {'Tx leak [fs]':>13s} {'local [fs]':>11s} {'clock path [fs]':>16s} {'total [fs]':>11s}")
for bw, b in sw[::5]:
    print(f"{bw:12.0e} {1e15 * b.common_leak_s:13.1f} {1e15 * b.local_pll_s:11.1f} {1e15 * b.clock_path_s:16.1f} "
          f"{1e15 * b.total_s:11.1f}")
print(f"optimum near {best[0]:.1e} Hz: {1e15 * best[1].total_s:.1f} fs "
      f"(vs {1e15 * sw[0][1].total_s:.1f} fs at {sw[0][0]:.0e} Hz, where the Tx PLL leaks, and "
      f"{1e15 * sw[-1][1].total_s:.1f} fs at {sw[-1][0]:.0e} Hz, where the clock path passes)")

print(f"\nper-lane tracker: latency and phase-interpolator step at 2 MHz (module clocking, "
      f"{1e15 * ck.data_path_wander_s:.0f} fs wander per path):")
print(f"{'latency [UI]':>12s} {'PI step [UI]':>12s} {'linear [fs]':>12s} {'+quantisation [fs]':>19s} {'eye width [UI]':>15s}")
for d, step in ((0, 0.0), (4, 0.0), (32, 0.0), (0, 1 / 64), (4, 1 / 64), (4, 1 / 16)):
    c = dataclasses.replace(base, clocking=dataclasses.replace(ck, track_delay_ui=d, pi_step_ui=step))
    f2 = ForwardedClock(c)
    s = run_statistical(c)
    lin, q = f2.residual_sigma_s(), f2.quantisation_sigma_s()
    print(f"{d:12d} {step:12.4f} {1e15 * lin:12.1f} {1e15 * math.hypot(lin, q):19.1f} {s.eye_width_ui:15.3f}")

plt = plt_or_none()
if plt is not None:
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.loglog(bws, [1e15 * b.common_leak_s for _, b, _ in rows], "o-", label="Tx PLL leak")
    ax.loglog(bws, [1e15 * b.local_pll_s for _, b, _ in rows], "s-", label="local PLL above the loop")
    ax.loglog(bws, [1e15 * b.total_s for _, b, _ in rows], "k-", lw=2, label="total residual")
    ax.loglog([bw for bw, _ in sw], [1e15 * b.total_s for _, b in sw], "--", color="gray",
              label="300 fs white clock-path jitter, ideal tree")
    ax.set_xlabel("local PLL loop bandwidth [Hz]")
    ax.set_ylabel("residual at the sampler [fs RMS]")
    ax.set_title("forwarded clock through a receiver PLL")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = OUT / "04_local_pll_bandwidth.png"
    fig.savefig(path, dpi=120)
    print(f"wrote {path}")
