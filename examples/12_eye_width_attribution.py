"""Example 12: where each bundled module's eye width goes.

Since 0.13.6 every bundled 32 GT/s config fails on eye width, not height. The
far-end crosstalk is the aggressor's derivative: it lifts the eye's height
and eats its edges. This example splits each config's worst-lane eye-width
gap into its causes with ``report.attribution`` (also
``tools/budget_report.py --attribution``). The model is not changed; each
cause is switched off by a replace of the config (``report.switched_off``):

- **crosstalk**: ``channel.xtalk`` and ``xtalk_next`` to ``none``;
- **jitter**: every clock-path term set to zero -- both PLL profiles and
  their white parts, the data / clock path white and wander terms, the
  tree's own jitter, DCD. The tracker and the tree's delay stay, but with
  nothing to track they cost nothing;
- **PI step**: ``clocking.pi_step_ui`` 0 with ``lanes.deskew_with_tracker:
  ideal`` (the deskew step is the interpolator's step since 0.13.0).

With all three off what is left is the channel's ISI and the receiver
noise: the eye the line itself allows.

The causes interact -- crosstalk on the edges costs more width once jitter
has pushed the bathtub's walls in -- so one-at-a-time numbers do not add up.
The split printed is the Shapley value: each cause's gain averaged over
every order of switching them off. The shares sum exactly to the gap
between the full eye and the ISI-only eye. "Alone off" is the eye with only
that cause switched off: does removing it pass the link?

The bundled configs are covered, plus example 05's x64 with the behavioural
FEXT preset switched on (its config leaves crosstalk off).
"""

import dataclasses

from _common import CONFIGS, OUT, plt_or_none
from d2d_link.config import load_config
from d2d_link.report import attribution

R = dataclasses.replace
NAMES = ("standard_32g_x1", "standard_32g_x16_module", "standard_32g_x16_repair", "advanced_32g_x64_spare",
         "standard_32g_x5_coupled")


def configs():
    for name in NAMES:
        yield name, load_config(CONFIGS / f"{name}.yaml")
    adv = load_config(CONFIGS / "advanced_32g_x64_spare.yaml")
    yield "advanced_32g_x64_spare + fext", R(adv, channel=R(adv.channel, xtalk="fext"), sim=R(adv.sim, stat_phase_points=32))


rows = {}
for name, cfg in configs():
    a = attribution(cfg)
    rows[name] = a
    gap = a["ideal_ui"] - a["full_ui"]
    print(f"{name}: {cfg.lanes.count} lanes, {cfg.channel.length_mm:g} mm, crosstalk {cfg.channel.xtalk}, "
          f"PI step {cfg.pi_step_ui:.4f} UI")
    print(f"  worst-lane eye width {a['full_ui']:.4f} UI (lane {a['worst_lane']}); ISI and noise alone {a['ideal_ui']:.4f} UI "
          f"(lane {a['ideal_lane']}); gap {gap:.4f} UI; target {a['target_ui']:g} UI -> "
          + ("PASS" if a["full_ui"] >= a["target_ui"] else f"{a['target_ui'] - a['full_ui']:.4f} UI short"))
    print(f"  {'cause':>10s} {'share [UI]':>11s} {'of gap':>7s} {'alone off [UI]':>15s} {'alone passes':>13s}")
    for i in a["causes"]:
        alone = a["alone_off_ui"][i]
        print(f"  {i:>10s} {a['share_ui'][i]:11.4f} {a['share_ui'][i] / gap:7.0%} {alone:15.4f} "
              f"{'yes' if alone >= a['target_ui'] else 'no':>13s}")
    print(f"  shares sum to {sum(a['share_ui'].values()):.4f} UI (= the gap, by construction)")
    if a["ideal_ui"] < a["target_ui"]:
        print("  even with every cause off the line's own ISI misses the target")
    print()

print("summary: the largest share per config, and whether any single cause switched off passes")
for name, a in rows.items():
    top = max(a["share_ui"], key=a["share_ui"].get)
    fixes = [i for i in a["causes"] if a["alone_off_ui"][i] >= a["target_ui"]]
    print(f"  {name:31s} {top:>10s} {a['share_ui'][top]:.4f} UI of {a['ideal_ui'] - a['full_ui']:.4f}; "
          f"one cause off passes: {', '.join(fixes) if fixes else 'none'}")

plt = plt_or_none()
if plt is not None:
    colours = {"jitter": "C0", "crosstalk": "C3", "PI step": "C2"}
    fig, ax = plt.subplots(figsize=(9, 3.8))
    seen = set()
    for y, (name, a) in enumerate(rows.items()):
        ax.barh(y, a["full_ui"], color="0.75", label="today" if y == 0 else None)
        left = a["full_ui"]
        for i in a["causes"]:
            ax.barh(y, a["share_ui"][i], left=left, color=colours[i], label=None if i in seen else i)
            seen.add(i)
            left += a["share_ui"][i]
    ax.axvline(next(iter(rows.values()))["target_ui"], color="k", lw=0.8)
    ax.set_yticks(range(len(rows)), [n.replace("standard_32g_", "std ").replace("advanced_32g_", "adv ") for n in rows],
                  fontsize=8)
    ax.set_xlabel("worst-lane eye width [UI]: grey = today, coloured = what each cause takes (Shapley)")
    ax.set_xlim(0.5, 1.0)
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT / "12_eye_width_attribution.png", dpi=120)
    print("wrote examples/output/12_eye_width_attribution.png")
