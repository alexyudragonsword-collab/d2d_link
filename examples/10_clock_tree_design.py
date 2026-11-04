"""Example 10: how short must the clock tree be, and how low the Tx PLL's floor,
for the 32 GT/s standard-package link to pass?

Since 0.13.0 the bundled links fail the 0.75 UI eye-width target. The reason is
the forwarded clock's own tree. Data and clock leave the die on the same Tx PLL.
The receiver samples the data with the clock after its distribution tree (delay
tau, a first-order bandwidth on its phase). So what reaches the sampler is the
PLL's phase noise through ``1 - G(f)``, with ``G = exp(-j2 pi f tau) / (1 + jf/f_t)``.
Below about ``1/(6 tau)`` that difference is small, and forwarding tracks the
PLL. Near ``fs/2`` a 30 ps tree (about 1 UI) gives G close to -1: there,
forwarding *doubles* the PLL's high-frequency floor instead of cancelling it.
How much floor there is to double depends on two things:

- **the floor's level.** The bundled Tx PLL profile (a pll_simulator linear
  model of a 10.24 GHz SSPLL) flattens to -145.0 dBc/Hz above about 300 MHz.
  The variants here take that white floor off and put another one on
  (``S = max(S - S_-145, 0) + S_floor``), keeping the in-band shape. They are
  design targets, not measured PLLs.
- **the profile's reading above its last point** (``clocking.profile_above``).
  ``floor`` holds the last level flat out to fs/2 (the default since 0.13.0;
  the profile ends at f0/2 = 5.12 GHz, the sampler sees to 16 GHz).
  ``zero`` drops it there (0.12 and earlier). The profile file says nothing
  between 5.12 and 16 GHz, so the reading is a modelling choice; this example
  shows how much of the verdict it carries.

Four readings, each a dataclass replace of a bundled config. The variant
profiles are written to a temporary directory and named by
``clocking.pll_profile``, the same as any profile (invariant #1). The model
is not changed.

1. **The leak in closed form.** The common-mode leak (Tx PLL noise that the
   tree lets through) against tree delay, for x1 and for the x16 module.
2. **x1 eye width against tree delay** (tree bandwidth 20 GHz as bundled),
   for three floors and both readings, and the longest tree that passes.
3. **The tree's bandwidth.** A slower tree filters the clock path's own
   jitter but adds phase lag, which acts like delay. The longest passing
   tree for flat / 40 / 20 / 10 GHz trees, on the floor reading.
4. **The x16 module.** Its receiver's local PLL (1 MHz natural frequency)
   re-times the forwarded clock: above 1 MHz the Tx PLL's floor reaches the
   sampler on the data path alone, whatever the tree. The module's verdict
   against the floor, at two tree delays.
"""

import dataclasses
import math

import numpy as np
import yaml

from _common import CONFIGS, OUT, pll_floor_variant, plt_or_none
from d2d_link.clock.forwarded import ForwardedClock, resolve_data_file
from d2d_link.config import load_config
from d2d_link.engine import run_link, run_statistical

x1 = load_config(CONFIGS / "standard_32g_x1.yaml")
x16 = load_config(CONFIGS / "standard_32g_x16_module.yaml")
FLOORS = (-145.0, -150.0, -155.0)
READINGS = ("floor", "zero")
DELAYS = np.arange(0.0, 40.0 + 1e-9, 5.0)
TREE_BWS = (None, 40e9, 20e9, 10e9)
BUNDLED_FLOOR = -145.0         # the profile's asymptote: l_dbc_hz -> -145.0 at 5.12 GHz


# ------------------------------------------------------- the floor variants
src = resolve_data_file(x1.clocking.pll_profile)
base = yaml.safe_load(src.read_text())
PROFILES = {fl: pll_floor_variant(x1.clocking.pll_profile, fl, BUNDLED_FLOOR) for fl in FLOORS}


def clocked(cfg, floor_dbc, reading, tau_ps=None, tree_bw="keep"):
    kw = {"pll_profile": PROFILES[floor_dbc], "profile_above": reading}
    if tau_ps is not None:
        kw["tree_delay_ps"] = float(tau_ps)
    if tree_bw != "keep":
        kw["tree_bw_hz"] = tree_bw
    return dataclasses.replace(cfg, clocking=dataclasses.replace(cfg.clocking, **kw))


def bw_label(bw):
    return "flat" if bw is None else f"{bw / 1e9:g} GHz"


ref = run_statistical(x1)
ew_target = ref.targets["eye_width_ui"][0]
eh_target = ref.targets["eye_height_mv"][0]
print(f"x1 {x1.package.kind} package, {x1.channel.length_mm:g} mm, {x1.data_rate_gtps:g} GT/s; "
      f"bundled tree {x1.clocking.tree_delay_ps:g} ps / {bw_label(x1.clocking.tree_bw_hz)}; "
      f"targets {ew_target:g} UI / {eh_target:g} mV at BER {ref.target_ber:g}")
print(f"Tx PLL profile {src.name}: floor {BUNDLED_FLOOR:g} dBc/Hz above ~300 MHz, last point "
      f"{base['f_hz'][-1] / 1e9:g} GHz; the sampler sees to fs/2 = {x1.f_nyquist / 1e9:g} GHz\n")

# ------------------------------------------------- 1. the leak, closed form
print("1. common-mode leak [fs] (Tx PLL noise through 1 - G) against tree delay, closed form")
print(f"{'link':>5s} {'floor':>6s} {'reading':>8s} " + " ".join(f"{t:>6g}" for t in DELAYS[::2]) + "   tree delay [ps]")
leak = {}
for name, cfg in (("x1", x1), ("x16", x16)):
    for fl in FLOORS:
        for rd in READINGS:
            row = [1e15 * ForwardedClock(clocked(cfg, fl, rd, t)).budget().common_leak_s for t in DELAYS]
            leak[name, fl, rd] = row
            print(f"{name:>5s} {fl:6g} {rd:>8s} " + " ".join(f"{v:6.1f}" for v in row[::2]))
ratios = [leak["x1", fl, "floor"][i] / leak["x1", fl, "zero"][i] for fl in FLOORS for i in range(len(DELAYS))]
print(f"  x1: the leak grows with the tree; the floor reading carries {min(ratios):.1f}-{max(ratios):.1f}x the zero reading's "
      f"(the {base['f_hz'][-1] / 1e9:g}-{x1.f_nyquist / 1e9:g} GHz band only the floor reading fills is most of it)")
print(f"  x16: flat in tree delay -- its local PLL ({x16.clocking.local_pll_fn_hz / 1e6:g} MHz) re-times the clock, "
      "so the Tx floor above it is not tracked whatever the tree\n")


# ------------------------------------------- 2. x1 eye width vs tree delay
def x1_eye(fl, rd, tau, tree_bw="keep"):
    return run_statistical(clocked(x1, fl, rd, tau, tree_bw))


def longest_passing(fl, rd, tree_bw="keep", grid=None):
    """The longest tree delay in [0, 40] ps whose x1 eye passes: the grid's
    last passing point, then regula falsi on the eye width to 0.05 ps (the
    width falls monotonically with the delay in this range)."""
    widths = grid if grid is not None else [x1_eye(fl, rd, t, tree_bw).eye_width_ui for t in DELAYS]
    ok = [w >= ew_target for w in widths]
    if not ok[0]:
        return 0.0, False
    if all(ok):
        return float(DELAYS[-1]), True
    i = ok.index(False)
    a, b, wa, wb = float(DELAYS[i - 1]), float(DELAYS[i]), widths[i - 1], widths[i]
    while b - a > 0.05:
        m = a + (wa - ew_target) * (b - a) / (wa - wb)
        m = min(max(m, a + 0.01), b - 0.01)
        wm = x1_eye(fl, rd, m, tree_bw).eye_width_ui
        if wm >= ew_target:
            a, wa = m, wm
        else:
            b, wb = m, wm
    return a, False


print(f"2. x1 eye width [UI] against tree delay (tree {bw_label(x1.clocking.tree_bw_hz)}); eye height stays within "
      f"{x1_eye(-145.0, 'floor', 40.0).eye_height_v * 1e3:.1f}..{x1_eye(-155.0, 'zero', 0.0).eye_height_v * 1e3:.1f} mV")
print(f"{'floor':>6s} {'reading':>8s} " + " ".join(f"{t:>6g}" for t in DELAYS) + "   longest passing tree")
curves, longest = {}, {}
for fl in FLOORS:
    for rd in READINGS:
        res = [x1_eye(fl, rd, t) for t in DELAYS]
        curves[fl, rd] = [r.eye_width_ui for r in res]
        tau, whole = longest_passing(fl, rd, grid=curves[fl, rd])
        longest[fl, rd, x1.clocking.tree_bw_hz] = (tau, whole)
        verdict = "none passes" if tau == 0.0 and curves[fl, rd][0] < ew_target else (
            f">= {tau:g} ps (all)" if whole else f"{tau:.1f} ps")
        print(f"{fl:6g} {rd:>8s} " + " ".join(f"{w:6.3f}" for w in curves[fl, rd]) + f"   {verdict}")
i_b = int(np.argmin(np.abs(DELAYS - x1.clocking.tree_delay_ps)))
ok_b = [f"{fl:g} / {rd}" for (fl, rd), w in curves.items() if w[i_b] >= ew_target]
no_b = [f"{fl:g} / {rd}" for (fl, rd), w in curves.items() if w[i_b] < ew_target]
print(f"  the bundled {x1.clocking.tree_delay_ps:g} ps tree passes with {', '.join(ok_b)} and fails with {', '.join(no_b)} "
      "(floor dBc/Hz / reading)\n")

# --------------------------------------------------- 3. the tree's bandwidth
print("3. longest passing x1 tree [ps] against the tree's bandwidth (floor reading)")
print(f"{'floor':>6s} " + " ".join(f"{bw_label(bw):>9s}" for bw in TREE_BWS))
for fl in FLOORS:
    cells = []
    for bw in TREE_BWS:
        key = (fl, "floor", bw)
        if key not in longest:
            longest[key] = longest_passing(fl, "floor", bw)
        tau, whole = longest[key]
        first = x1_eye(fl, "floor", 0.0, bw).eye_width_ui
        cells.append("none" if first < ew_target else (f">= {tau:g}" if whole else f"{tau:.1f}"))
    print(f"{fl:6g} " + " ".join(f"{c:>9s}" for c in cells))
gd = {bw: (0.0 if bw is None else 1e12 / (2.0 * math.pi * bw)) for bw in TREE_BWS}
print("  a first-order tree at f_t lags its phase like a delay of 1/(2 pi f_t) at low frequency ("
      + ", ".join(f"{bw_label(bw)} {gd[bw]:.1f} ps" for bw in TREE_BWS if bw is not None)
      + "), and it filters the clock path's own jitter: the two pull against each other\n")

# -------------------------------------------------------- 4. the x16 module
print(f"4. x16 module ({x16.channel.length_mm:g} mm, crosstalk {x16.channel.xtalk}, local PLL "
      f"{x16.clocking.local_pll_fn_hz / 1e6:g} MHz): worst lane against the floor")
print(f"{'floor':>6s} {'reading':>8s} {'tree [ps]':>9s} {'leak [fs]':>10s} {'eye width min [UI]':>19s} "
      f"{'eye height min [mV]':>20s} {'link':>5s}")
module = {}
points = [(fl, rd, x16.clocking.tree_delay_ps) for fl in FLOORS for rd in READINGS] + [(-145.0, "floor", 0.0)]
for fl, rd, tau in points:
    c = clocked(x16, fl, rd, tau)
    res = run_link(c)
    module[fl, rd, tau] = res
    lk = 1e15 * ForwardedClock(c).budget().common_leak_s
    print(f"{fl:6g} {rd:>8s} {tau:9g} {lk:10.1f} {res.eye_width_min_ui:19.3f} {1e3 * res.eye_height_min_v:20.1f} "
          f"{'PASS' if res.passes else 'FAIL':>5s}")
for fl in (FLOORS[0], FLOORS[-1]):
    b = ForwardedClock(clocked(x16, fl, "floor")).budget()
    parts = {"Tx leak": b.common_leak_s, "local PLL": b.local_pll_s, "data path": b.data_path_s,
             "data wander": b.data_wander_s, "clock path": b.clock_path_s, "clock wander": b.clock_wander_s,
             "tree": b.tree_s, "spurs": b.spur_s}
    print(f"  budget at {fl:g} dBc/Hz (floor reading): total {1e15 * b.total_s:.1f} fs = "
          + " + ".join(f"{k} {1e15 * v:.1f}" for k, v in parts.items() if v > 0.0) + " fs (in power)")
d_tau = module[-145.0, "floor", 0.0].eye_width_min_ui - module[-145.0, "floor", x16.clocking.tree_delay_ps].eye_width_min_ui
print(f"  a {x16.clocking.tree_delay_ps:g} ps shorter tree moves the module's eye by {d_tau:+.4f} UI: "
      "on the module, the local PLL's bandwidth sets how much of the Tx floor is tracked (example 04),")
best = max(module.values(), key=lambda r: r.eye_width_min_ui)
print(f"  and the floor alone does not pass it: the best point here reads {best.eye_width_min_ui:.3f} UI; "
      "the rest of its budget (wander, the local PLL's own noise, crosstalk, the PI step) is what stays\n")

# ------------------------------------------------------------------ figure
plt = plt_or_none()
if plt is not None:
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.2))
    colours = {-145.0: "C3", -150.0: "C1", -155.0: "C2"}
    for (fl, rd), w in curves.items():
        a.plot(DELAYS, w, color=colours[fl], ls="-" if rd == "floor" else "--", marker="o", ms=3,
               label=f"{fl:g} dBc/Hz, {rd}")
    a.axhline(ew_target, color="k", lw=0.8)
    a.axvline(x1.clocking.tree_delay_ps, color="0.6", lw=0.8, ls=":")
    a.set_xlabel("clock tree delay [ps]")
    a.set_ylabel("x1 eye width at target BER [UI]")
    a.set_title(f"x1, tree {bw_label(x1.clocking.tree_bw_hz)}: solid = floor reading, dashed = zero")
    a.legend(fontsize=7)
    xs = np.arange(len(TREE_BWS))
    for k, fl in enumerate(FLOORS):
        ys = [longest[fl, "floor", bw][0] for bw in TREE_BWS]
        b.bar(xs + (k - 1) * 0.25, ys, width=0.25, color=colours[fl], label=f"{fl:g} dBc/Hz")
    b.set_xticks(xs, [bw_label(bw) for bw in TREE_BWS])
    b.axhline(x1.clocking.tree_delay_ps, color="0.6", lw=0.8, ls=":")
    b.set_xlabel("clock tree bandwidth")
    b.set_ylabel("longest passing x1 tree [ps]")
    b.set_title("x1, floor reading (40 = the sweep's end)")
    b.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "10_clock_tree_design.png", dpi=120)
    print("wrote examples/output/10_clock_tree_design.png")
