"""Example 07: every data rate of the survey table, both packages, the whole module.

The rates a UCIe link can run at are in the survey table (``data_rates_gtps``,
source: survey). For each of them the standard package is run at its survey
reach (25 mm) and the advanced package at its (2 mm), as a five-lane module
with the coupled-line crosstalk estimate (the pitch is the package's bump
pitch from the same table) and the milestone-2 clocking, and the middle
lane -- the one with two neighbours on each side -- is reported: eye height
and width at the target BER, the residual jitter as a fraction of the UI,
and the verdict against the survey targets. The budget report tool writes
the 32 GT/s standard-package case out in full.

The UI shrinks with the rate while the jitter in seconds does not, and the
coupled FEXT grows with the Nyquist frequency: the table shows where each
package runs out, and on which of the two eye targets.
"""

import dataclasses
import importlib.util
import sys

from _common import CONFIGS, OUT, REPO, plt_or_none
from d2d_link.channel.coupled import describe
from d2d_link.config import load_config
from d2d_link.engine import run_link
from d2d_link.spec import survey

rates = survey("data_rates_gtps")
print(f"data rates {rates.value} {rates.unit} (source: {rates.source})")

# the x5 module at the standard package's survey reach is a config file of its
# own (ROADMAP P1 #2 reproduces from it); the advanced case is the same module
# on the other package, at that package's survey reach
module = load_config(CONFIGS / "standard_32g_x5_coupled.yaml")
adv_reach = float(survey("reach_mm", "advanced").value)
cases = {"standard": module,
         "advanced": dataclasses.replace(module, package=dataclasses.replace(module.package, kind="advanced"),
                                         channel=dataclasses.replace(module.channel, length_mm=adv_reach),
                                         clocking=dataclasses.replace(module.clocking, tree_delay_ps=15.0, tree_bw_hz=25e9))}

results = {}
for name, cfg in cases.items():
    reach = survey("reach_mm", cfg.package.kind)
    x = describe(cfg)
    print(f"\n{name} package at {cfg.channel.length_mm:g} mm (survey reach {reach.value:g} mm): pitch {x['pitch_um']:g} um "
          f"(source: {x['pitch_source']}), FEXT estimate {x['fext_adjacent_db']:.1f} dB at Nyquist for 32 GT/s")
    print(f"{'GT/s':>5s} {'UI [ps]':>8s} {'IL@Nyq [dB]':>12s} {'FEXT [dB]':>10s} {'jitter [UI]':>12s} {'eye height [mV]':>16s} "
          f"{'eye width [UI]':>15s} {'BER':>10s} {'pass':>5s}")
    rows = []
    for rate in rates.value:
        c = dataclasses.replace(cfg, data_rate_gtps=float(rate))
        res = run_link(c)
        mid = res.stat[2]
        rows.append((rate, mid, res.passes))
        print(f"{rate:5g} {1e12 * c.ui:8.2f} {mid.extras['insertion_loss_nyquist_db']:12.2f} {c.xtalk_db()[0]:10.1f} "
              f"{mid.sigma_jitter_s / c.ui:12.4f} {1e3 * mid.eye_height_v:16.1f} {mid.eye_width_ui:15.3f} "
              f"{mid.ber:10.1e} {'yes' if res.passes else 'no':>5s}")
    results[name] = rows
    fails = [(r, m) for r, m, ok in rows if not ok]
    if fails:
        r, m = fails[0]
        why = "eye width" if m.eye_width_margin_ui < 0 else ("eye height" if m.eye_height_margin_mv < 0 else "BER")
        print(f"  first failing rate {r:g} GT/s, limited by {why} "
              f"(eye {1e3 * m.eye_height_v:.1f} mV / {m.eye_width_ui:.3f} UI vs targets "
              f"{m.targets['eye_height_mv'][0]:g} mV / {m.targets['eye_width_ui'][0]:g} UI, source: {m.targets['eye_width_ui'][1]})")
    else:
        print("  every rate passes")

spec = importlib.util.spec_from_file_location("budget_report", REPO / "tools" / "budget_report.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
rep = tool.build(cases["standard"])            # the config's own rate (32 GT/s)
path = OUT / "07_budget_standard_32g.md"
path.write_text(tool.to_markdown(rep), encoding="utf-8")
terms = {r["term"]: r["fs"] for r in rep["jitter_budget"]}
print(f"\nbudget report for the standard package at 32 GT/s: {path.name}; total {terms['total (power sum)']:.1f} fs of which "
      f"Tx leak {terms['Tx PLL common-mode leak (tree, local PLL, rho)']:.1f}, local PLL {terms['local PLL own noise above its loop']:.1f}, "
      f"quantisation {terms['phase-interpolator quantisation (uniform)']:.1f} fs")
sys.stdout.flush()

plt = plt_or_none()
if plt is not None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for name, rows in results.items():
        axes[0].plot([r for r, _, _ in rows], [1e3 * m.eye_height_v for _, m, _ in rows], "o-", label=name)
        axes[1].plot([r for r, _, _ in rows], [m.eye_width_ui for _, m, _ in rows], "o-", label=name)
    t = results["standard"][0][1].targets
    axes[0].axhline(t["eye_height_mv"][0], color="r", ls="--", lw=0.8, label=f"target (source: {t['eye_height_mv'][1]})")
    axes[1].axhline(t["eye_width_ui"][0], color="r", ls="--", lw=0.8, label=f"target (source: {t['eye_width_ui'][1]})")
    axes[0].set_xlabel("data rate [GT/s]")
    axes[1].set_xlabel("data rate [GT/s]")
    axes[0].set_ylabel("eye height at 1e-27 [mV]")
    axes[1].set_ylabel("eye width at 1e-27 [UI]")
    axes[0].set_title("middle lane of a x5 module, coupled FEXT")
    axes[0].legend(fontsize=8)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    png = OUT / "07_rate_sweep.png"
    fig.savefig(png, dpi=120)
    print(f"wrote {png}")
