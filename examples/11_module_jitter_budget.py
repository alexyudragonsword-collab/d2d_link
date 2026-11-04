"""Example 11: what jitter can the x16 module afford, and where can it come from?

Example 10 found that on the x16 module the clock tree's length does nothing.
The receiver's local PLL (1 MHz natural frequency) re-times the forwarded
clock, so the Tx PLL's floor above it is not tracked whatever the tree. Even a
-155 dBc/Hz floor leaves the worst lane at 0.733 UI. This example asks the
module's own question: how much residual jitter can it afford, and which
design levers buy the difference?

1. **The affordable sigma.** Everything else held (crosstalk, skew residual,
   the 1/64 UI PI step, noise), the worst lane's eye width falls with the
   Gaussian RMS of the sampling residual alone. The curve is read by varying
   one white term (the data path's ``data_path_rj_s``), and sigma* is where
   it crosses the 0.75 UI target.
2. **Levers one at a time**, in closed form (``ForwardedClock.budget``):
   - the Tx PLL floor (variants as in example 10);
   - the per-lane tracker's bandwidth;
   - the local PLL's natural frequency;
   - the paths' wander;
   - the data path's white jitter;
   - the tree's own jitter.

   For each: the total sigma, and the eye the curve in (1) predicts.
3. **Combinations**: floor x tracker x data path x wander, predicted
   pass / fail.
4. **Confirmation**: full module runs on combinations either side of the
   line, predicted against computed eye width. The statistical engine sees
   the residual as one Gaussian sigma (plus the PI step's box and the
   spurs), so the reading in (1) is exact by construction, not an
   approximation. What (4) checks is the bookkeeping: the closed form and
   the engine agree, and the worst lane does not change. The jitter's
   spectrum matters only to the time engine.

No model change; every point is a dataclass replace of
``configs/standard_32g_x16_module.yaml``, floor variants through
``clocking.pll_profile``.
"""

import dataclasses
import itertools

import numpy as np

from _common import CONFIGS, OUT, pll_floor_variant, plt_or_none
from d2d_link.clock.forwarded import ForwardedClock
from d2d_link.config import load_config
from d2d_link.engine import run_link

x16 = load_config(CONFIGS / "standard_32g_x16_module.yaml")
ck0 = x16.clocking


def clocked(**kw):
    if "floor" in kw:
        kw["pll_profile"] = pll_floor_variant(ck0.pll_profile, kw.pop("floor"))
    return dataclasses.replace(x16, clocking=dataclasses.replace(ck0, **kw))


def sigma_fs(cfg) -> float:
    return 1e15 * ForwardedClock(cfg).budget().total_s


base = run_link(x16)
ew_target = base.worst.targets["eye_width_ui"][0]
b0 = ForwardedClock(x16).budget()
TERMS = {"Tx leak": "common_leak_s", "local PLL": "local_pll_s", "data path": "data_path_s",
         "data wander": "data_wander_s", "clock path": "clock_path_s", "clock wander": "clock_wander_s",
         "tree": "tree_s", "spurs": "spur_s"}
print(f"x16 {x16.package.kind} package, {x16.channel.length_mm:g} mm, {x16.data_rate_gtps:g} GT/s, crosstalk {x16.channel.xtalk}, "
      f"PI step {x16.pi_step_ui:g} UI; local PLL {ck0.local_pll_fn_hz / 1e6:g} MHz, tracker {ck0.track_bw_hz / 1e6:g} MHz "
      f"({ck0.track_delay_ui} UI latency)")
print(f"bundled residual {1e15 * b0.total_s:.1f} fs = "
      + " + ".join(f"{k} {1e15 * getattr(b0, a):.1f}" for k, a in TERMS.items() if getattr(b0, a) > 0.0) + " fs (in power)")
print(f"worst lane {base.worst.lane}: {base.eye_width_min_ui:.4f} UI against {ew_target:g} UI -> link {'PASS' if base.passes else 'FAIL'}\n")

# ------------------------------------------------- 1. the affordable sigma
print("1. worst-lane eye width against the residual's Gaussian RMS (varying the data path's white jitter only)")
print(f"{'data_path_rj [fs]':>18s} {'sigma [fs]':>11s} {'eye width min [UI]':>19s} {'worst lane':>11s}")
curve = []                                                  # (sigma fs, eye width UI)
by_rj = {}
for rj in (0.0, 100.0, 150.0, 200.0, 250.0):
    c = clocked(data_path_rj_s=rj * 1e-15)
    r = base if rj * 1e-15 == ck0.data_path_rj_s else run_link(c)
    curve.append((sigma_fs(c), r.eye_width_min_ui))
    by_rj[rj] = r.eye_width_min_ui
    print(f"{rj:18g} {curve[-1][0]:11.1f} {r.eye_width_min_ui:19.4f} {r.worst.lane:11d}")
curve.sort()
sig, ew = np.array(curve).T
# sigma*: regula falsi on the data path's term between the bracketing points
lo, hi = 0.0, 100.0
w_lo, w_hi = by_rj[lo], by_rj[hi]
if w_lo < ew_target:
    raise SystemExit("even a noiseless data path does not open the module to the target")
for _ in range(6):
    m = lo + (w_lo - ew_target) * (hi - lo) / (w_lo - w_hi)
    wm = run_link(clocked(data_path_rj_s=m * 1e-15)).eye_width_min_ui
    if abs(wm - ew_target) < 2e-4:
        break
    if wm >= ew_target:
        lo, w_lo = m, wm
    else:
        hi, w_hi = m, wm
sigma_star = sigma_fs(clocked(data_path_rj_s=m * 1e-15))
curve.append((sigma_star, wm))
curve.sort()
sig, ew = np.array(curve).T
print(f"  sigma* = {sigma_star:.1f} fs (eye {wm:.4f} UI at data_path_rj {m:.1f} fs): the module affords {sigma_star:.0f} fs "
      f"against {1e15 * b0.total_s:.1f} fs today -- {np.sqrt((1e15 * b0.total_s) ** 2 - sigma_star ** 2):.0f} fs "
      f"(in power) has to go\n")


def predicted(s: float) -> float:
    """The worst lane's eye at residual sigma ``s`` read off the curve (nan
    below the curve's lowest point: a noiseless data path is its end)."""
    return float(np.interp(s, sig, ew)) if s >= sig[0] else float("nan")


def fmt_pred(s: float) -> str:
    v = predicted(s)
    return f"> {ew[0]:.4f}" if np.isnan(v) else f"{v:.4f}"


# ------------------------------------------------------ 2. levers one by one
LEVERS = [
    ("bundled", {}),
    ("Tx PLL floor -150 dBc/Hz", {"floor": -150.0}),
    ("Tx PLL floor -155 dBc/Hz", {"floor": -155.0}),
    ("tracker 5 MHz", {"track_bw_hz": 5e6}),
    ("tracker 10 MHz", {"track_bw_hz": 10e6}),
    ("local PLL 0.1 MHz", {"local_pll_fn_hz": 1e5}),
    ("local PLL 10 MHz", {"local_pll_fn_hz": 1e7}),
    ("wander 100 fs per path", {"data_path_wander_s": 100e-15, "clock_path_wander_s": 100e-15}),
    ("no wander", {"data_path_wander_s": 0.0, "clock_path_wander_s": 0.0}),
    ("data path 100 fs", {"data_path_rj_s": 100e-15}),
    ("tree jitter 50 fs", {"tree_rj_s": 50e-15}),
]
print(f"2. levers one at a time (closed form; eye predicted from the curve in 1, sigma* {sigma_star:.1f} fs)")
print(f"{'lever':>26s} {'sigma [fs]':>11s} {'change [fs]':>12s} {'eye width [UI]':>15s} {'pass':>5s}")
lever_sigma = {}
for name, kw in LEVERS:
    s = sigma_fs(clocked(**dict(kw)))
    lever_sigma[name] = s
    print(f"{name:>26s} {s:11.1f} {s - lever_sigma['bundled']:+12.1f} {fmt_pred(s):>15s} {'yes' if s <= sigma_star else 'no':>5s}")
best_single = min(lever_sigma.items(), key=lambda kv: kv[1])
print(f"  no single lever reaches sigma*; the largest, '{best_single[0]}', leaves {best_single[1]:.1f} fs\n"
      if best_single[1] > sigma_star else f"  '{best_single[0]}' alone reaches sigma*\n")

# --------------------------------------------------------- 3. combinations
FLOORS = (-145.0, -150.0, -155.0)
TRACKERS = (2e6, 10e6)
DATA_RJ = (200e-15, 100e-15)
WANDER = (200e-15, 100e-15)
print("3. combinations, total sigma [fs] (* = within sigma*, predicted to pass)")
cols = list(itertools.product(DATA_RJ, WANDER))
print(f"{'floor':>6s} {'tracker':>8s} " + " ".join(f"{'dp ' + format(1e15 * d, 'g') + ' / w ' + format(1e15 * w, 'g'):>17s}"
                                            for d, w in cols))
combos = {}
for fl, tb in itertools.product(FLOORS, TRACKERS):
    cells = []
    for d, w in cols:
        kw = {"floor": fl, "track_bw_hz": tb, "data_path_rj_s": d, "data_path_wander_s": w, "clock_path_wander_s": w}
        s = sigma_fs(clocked(**dict(kw)))
        combos[fl, tb, d, w] = (s, kw)
        cells.append(f"{s:6.1f}{'*' if s <= sigma_star else ' '}")
    print(f"{fl:6g} {tb / 1e6:6g} M " + " ".join(f"{c:>17s}" for c in cells))
passing = sorted((v[0], k) for k, v in combos.items() if v[0] <= sigma_star)
print(f"  {len(passing)} of {len(combos)} combinations pass; at the bundled 200 fs data path and 200 fs wander none does"
      if not any(k[2] == 200e-15 and k[3] == 200e-15 for _, k in passing) else f"  {len(passing)} of {len(combos)} pass")
cheapest = [k for _, k in passing if k[0] == -145.0]
if cheapest:
    print("  at the bundled -145 dBc/Hz floor: " + "; ".join(
        f"tracker {k[1] / 1e6:g} MHz, data path {1e15 * k[2]:g} fs, wander {1e15 * k[3]:g} fs" for k in cheapest))
print()

# -------------------------------------------------------- 4. confirmation
fails = sorted((v[0], k) for k, v in combos.items() if v[0] > sigma_star)
picks = [passing[-1], passing[0], fails[0], fails[len(fails) // 2]] if passing and fails else []
print("4. confirmation: full module runs either side of the line")
print(f"{'floor':>6s} {'tracker':>8s} {'dp [fs]':>8s} {'wander':>7s} {'sigma [fs]':>11s} {'predicted [UI]':>15s} "
      f"{'computed [UI]':>14s} {'worst lane':>11s} {'link':>5s}")
confirm = []
for s, k in picks:
    r = run_link(clocked(**dict(combos[k][1])))
    confirm.append((s, r.eye_width_min_ui))
    print(f"{k[0]:6g} {k[1] / 1e6:6g} M {1e15 * k[2]:8g} {1e15 * k[3]:7g} {s:11.1f} {fmt_pred(s):>15s} "
          f"{r.eye_width_min_ui:14.4f} {r.worst.lane:11d} {'PASS' if r.passes else 'FAIL':>5s}")
if confirm:
    inside = [(s, w) for s, w in confirm if not np.isnan(predicted(s))]
    err = max(abs(predicted(s) - w) for s, w in inside)
    print(f"  largest prediction error on the curve's range {err:.4f} UI ({len(inside)} points): the statistical engine takes the "
          "residual as one Gaussian sigma, so the curve is exact whichever term the sigma comes from")
    print("  (a point below the curve's lowest sigma is only bounded from below by it)\n")

# ------------------------------------------------------------------ figure
plt = plt_or_none()
if plt is not None:
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1, 1.2]})
    a.plot(sig, ew, "o-", color="C0", label="data path's white jitter varied")
    if confirm:
        cs, cw = np.array(confirm).T
        a.plot(cs, cw, "s", color="C3", label="combinations (section 4)")
    a.axhline(ew_target, color="k", lw=0.8)
    a.axvline(sigma_star, color="0.5", lw=0.8, ls=":")
    a.set_xlabel("residual jitter, Gaussian RMS [fs]")
    a.set_ylabel("worst-lane eye width [UI]")
    a.set_title(f"x16 module: sigma* = {sigma_star:.0f} fs")
    a.legend(fontsize=7)
    names = [n for n, _ in LEVERS]
    vals = [lever_sigma[n] for n in names]
    b.barh(range(len(names)), vals, color=["C2" if v <= sigma_star else "C7" for v in vals])
    b.axvline(sigma_star, color="0.5", lw=0.8, ls=":")
    b.set_yticks(range(len(names)), names, fontsize=7)
    b.invert_yaxis()
    b.set_xlim(min(vals) * 0.8, max(vals) * 1.02)
    b.set_xlabel("residual jitter [fs] (closed form)")
    b.set_title("one lever at a time")
    fig.tight_layout()
    fig.savefig(OUT / "11_module_jitter_budget.png", dpi=120)
    print("wrote examples/output/11_module_jitter_budget.png")
