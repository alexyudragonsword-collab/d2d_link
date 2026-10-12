"""Example 05: a whole module -- skew, crosstalk, a dead lane and its repair.

``configs/standard_32g_x16_module.yaml`` is a standard-package x16 module at
20 mm: random lane skew (3 ps RMS) deskewed in 1/16-UI steps, far-end
crosstalk from the two neighbours on each side (package preset, -30 dB at
Nyquist for the nearest), the module's local PLL and tracker, and physical
lane 5 dead. Width degradation keeps the intact upper x8; the lanes at the
edges of that half have fewer neighbours than the ones inside it, and the
dead lane and the unused lower half are silent. Every active lane is run
through the statistical engine and the link is judged by its worst lane.

The second part does the same for the advanced package's x64 module with
spare-lane repair (two dead bumps, four spares), where the remapping moves
which lanes are neighbours. The third part switches crosstalk off to show
what it costs.
"""

import dataclasses

import numpy as np

from _common import CONFIGS, OUT, plt_or_none
from d2d_link.config import load_config
from d2d_link.engine import run_link


def report(res, title):
    lm = res.lanes
    print(f"\n{title}")
    print(f"  {lm.active_width}/{lm.requested_width} lanes active, repair {lm.mode}, failed {list(lm.failed)}"
          f"{', UNREPAIRED ' + str(list(lm.unrepaired)) if lm.unrepaired else ''}; link {'PASS' if res.passes else 'FAIL'}")
    print(f"  {'logical':>7s} {'physical':>8s} {'skew [ps]':>9s} {'residual [UI]':>13s} {'aggressors':>10s} "
          f"{'xtalk [mV]':>10s} {'eye height [mV]':>16s} {'eye width [UI]':>14s} {'BER':>10s}")
    for r, phys in zip(res.stat, [p for p in lm.logical_to_physical if p not in lm.unrepaired]):
        print(f"  {r.lane:7d} {phys:8d} {res.skew_ps[phys]:9.2f} {r.skew_residual_ui:13.4f} "
              f"{r.extras['n_aggressors']:10d} {1e3 * r.extras['xtalk_rms_v']:10.2f} {1e3 * r.eye_height_v:16.1f} "
              f"{r.eye_width_ui:14.3f} {r.ber:10.1e}")
    w = res.worst
    print(f"  worst lane {w.lane}: eye {1e3 * w.eye_height_v:.1f} mV / {w.eye_width_ui:.3f} UI vs targets "
          f"{res.targets['eye_height_mv'][0]:g} mV / {res.targets['eye_width_ui'][0]:g} UI "
          f"(source: {res.targets['eye_height_mv'][1]}); min eye height over lanes {1e3 * res.eye_height_min_v:.1f} mV")
    return res


cfg = load_config(CONFIGS / "standard_32g_x16_module.yaml")
res16 = report(run_link(cfg), f"standard package x16, {cfg.channel.length_mm:g} mm, lane 5 dead, width degradation")

adv = load_config(CONFIGS / "advanced_32g_x64_spare.yaml")
adv = dataclasses.replace(adv, channel=dataclasses.replace(adv.channel, xtalk="fext"),
                          sim=dataclasses.replace(adv.sim, stat_phase_points=32))
res64 = run_link(adv)
lm = res64.lanes
print(f"\nadvanced package x64, {adv.channel.length_mm:g} mm, lanes {list(lm.failed)} dead, {adv.lanes.spare_count} spares: "
      f"{lm.active_width}/{lm.requested_width} active, link {'PASS' if res64.passes else 'FAIL'}")
moved = [(lane, phys) for lane, phys in enumerate(lm.logical_to_physical) if lane != phys]
print(f"  {len(moved)} logical lanes remapped (first: logical {moved[0][0]} -> physical {moved[0][1]}); "
      f"physical neighbours of the dead lanes are now edge lanes with one neighbour fewer")
n_aggr = np.array([r.extras["n_aggressors"] for r in res64.stat])
eh = np.array([1e3 * r.eye_height_v for r in res64.stat])
print(f"  aggressors per lane: {np.bincount(n_aggr).tolist()} lanes with 0..{n_aggr.max()} neighbours; "
      f"eye height {eh.min():.1f}..{eh.max():.1f} mV, worst lane {res64.worst.lane} "
      f"(physical {lm.logical_to_physical[res64.worst.lane]}), eye width min {res64.eye_width_min_ui:.3f} UI")

quiet = run_link(dataclasses.replace(cfg, channel=dataclasses.replace(cfg.channel, xtalk="none")))
print(f"\ncrosstalk off on the x16 module: min eye height {1e3 * quiet.eye_height_min_v:.1f} mV "
      f"(on: {1e3 * res16.eye_height_min_v:.1f} mV), min eye width {quiet.eye_width_min_ui:.3f} UI "
      f"(on: {res16.eye_width_min_ui:.3f} UI)")
loud = run_link(dataclasses.replace(cfg, channel=dataclasses.replace(cfg.channel, xtalk_adjacent_db=-20.0)))
print(f"crosstalk at -20 dB instead of the preset -30 dB: min eye height {1e3 * loud.eye_height_min_v:.1f} mV, "
      f"min eye width {loud.eye_width_min_ui:.3f} UI, link {'PASS' if loud.passes else 'FAIL'}")

plt = plt_or_none()
if plt is not None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    ax = axes[0]
    phys = [p for p in res16.lanes.logical_to_physical]
    ax.bar(phys, [1e3 * r.eye_height_v for r in res16.stat], color="C0", label="crosstalk on")
    ax.bar(phys, [1e3 * r.eye_height_v for r in quiet.stat], color="none", edgecolor="C1", label="crosstalk off")
    ax.axhline(res16.targets["eye_height_mv"][0], color="r", ls="--", lw=0.8, label="target (survey)")
    ax.set_xlabel("physical lane")
    ax.set_ylabel("eye height at 1e-27 [mV]")
    ax.set_title("x16 standard, lane 5 dead -> upper x8")
    ax.legend(fontsize=8)
    ax = axes[1]
    ax.plot(lm.logical_to_physical, eh, "o", ms=3)
    for p in lm.failed:
        ax.axvline(p, color="r", ls=":", lw=0.8)
    ax.set_xlabel("physical lane")
    ax.set_ylabel("eye height at 1e-27 [mV]")
    ax.set_title("x64 advanced, spare repair (dead lanes dotted)")
    fig.tight_layout()
    path = OUT / "05_module_xtalk_repair.png"
    fig.savefig(path, dpi=120)
    print(f"wrote {path}")
