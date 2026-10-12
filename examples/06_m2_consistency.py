"""Example 06: statistical / time-domain consistency on the milestone-2 mechanisms.

Example 03 checked the two engines on noise and white jitter. The mechanisms
added since -- a local PLL whose noise is coloured, a tracker with latency and
a quantised phase interpolator, crosstalk from neighbour lanes with their own
data and skew, the advanced package's high-resistance line with a CTLE -- each
rest on an assumption the statistical engine makes (independence, Gaussian
tails, a uniform quantisation error). Here each is pushed to a BER the time
engine can count in a few million symbols, and the ratio reported; the
acceptance is 0.5-2x. The crosstalk point runs a x3 module and reports the
middle lane, which carries both aggressors.
"""

import dataclasses
import time

from _common import CONFIGS, plt_or_none
from d2d_link.config import load_config
from d2d_link.engine import run_link, run_statistical, run_time
from d2d_link.engine.statistical import StatisticalEngine

cfg = load_config(CONFIGS / "standard_32g_x16_module.yaml")
one = dataclasses.replace(cfg, lanes=dataclasses.replace(cfg.lanes, count=1, failed=(), repair="none", skew_sigma_ps=0.0),
                          channel=dataclasses.replace(cfg.channel, xtalk="none"))


def noise_for_ber(c, target):
    eng = StatisticalEngine(c)
    phase = eng.run().phase_ui
    lo, hi = 1e-4, 0.5
    for _ in range(40):
        mid = (lo * hi) ** 0.5
        eng.sigma_n = mid
        if eng.error_probability(phase) > target:
            hi = mid
        else:
            lo = mid
    return (lo * hi) ** 0.5


def point(name, c, n_symbols):
    t0 = time.time()
    s = run_statistical(c)
    t_stat = time.time() - t0
    t0 = time.time()
    td = run_time(dataclasses.replace(c, sim=dataclasses.replace(c.sim, n_symbols=n_symbols)), phase_ui=s.phase_ui)
    ratio = td.ber / s.ber if s.ber > 0 else float("inf")
    lo, hi = td.ber_ci95
    print(f"{name}: noise {1e3 * c.rx.noise_rms_v:.2f} mV, jitter {1e15 * s.sigma_jitter_s:.0f} fs"
          f"{' + PI step ' + str(c.clocking.pi_step_ui) + ' UI' if c.clocking.pi_step_ui else ''}, phase {s.phase_ui:+.4f} UI")
    print(f"  statistical {s.ber:.3e} [{t_stat:.1f}s]   time {td.ber:.3e} ({td.n_errors} errors in {td.error_bursts} "
          f"bursts / {td.n_symbols:.1e}, 95% {lo:.1e}..{hi:.1e}) [{time.time() - t0:.0f}s]   ratio {ratio:.2f} "
          f"-> {'within 0.5-2x' if 0.5 <= ratio <= 2.0 else 'OUTSIDE 0.5-2x'}")
    return s, td, ratio


results = []
# 1. the local PLL: both profiles raised 24 dB so coloured clock noise makes the errors
c = dataclasses.replace(one, clocking=dataclasses.replace(one.clocking, pll_shift_db=24.0, local_pll_shift_db=24.0,
                                                          local_pll_bw_hz=2e5, track_bw_hz=None, pi_step_ui=0.0,
                                                          data_path_wander_s=0.0, clock_path_wander_s=0.0))
c = dataclasses.replace(c, rx=dataclasses.replace(c.rx, noise_rms_v=noise_for_ber(c, 1e-5)))
results.append(point("local PLL, coloured clock noise", c, 4_000_000))

# 2. tracker with latency and a coarse phase interpolator, on white path jitter
c = dataclasses.replace(one, clocking=dataclasses.replace(one.clocking, data_path_rj_s=2e-12, clock_path_rj_s=2e-12,
                                                          track_bw_hz=5e8, track_delay_ui=4, pi_step_ui=1 / 32,
                                                          data_path_wander_s=0.0, clock_path_wander_s=0.0))
c = dataclasses.replace(c, rx=dataclasses.replace(c.rx, noise_rms_v=noise_for_ber(c, 1e-5)))
results.append(point("quantised, delayed tracker", c, 4_000_000))

# 3. path wander through the 2 MHz tracker (the module's own setting, raised).
# Wander is slow: the sampler sits off-centre for thousands of symbols at a
# time, so a wander-only point gives its errors in a few bursts and the count
# says little (a first cut at 5 ps per path read 0.30x from 113 errors in a
# handful of bursts). The receiver's noise decorrelates the errors; the
# wander is kept to a share of the margin.
c = dataclasses.replace(one, clocking=dataclasses.replace(one.clocking, data_path_wander_s=2.5e-12,
                                                          clock_path_wander_s=2.5e-12, wander_corner_hz=3e6, pi_step_ui=0.0))
c = dataclasses.replace(c, rx=dataclasses.replace(c.rx, noise_rms_v=noise_for_ber(c, 1e-5)))
results.append(point("path wander through the tracker", c, 4_000_000))

# 4. crosstalk: x3 module, strong coupling, the middle lane
x3 = dataclasses.replace(cfg, lanes=dataclasses.replace(cfg.lanes, count=3, failed=(), repair="none",
                                                        skew_ps=(0.0, 3.0, -2.0), skew_sigma_ps=0.0, deskew_step_ps=0.0),
                         channel=dataclasses.replace(cfg.channel, xtalk_adjacent_db=-14.0),
                         clocking=dataclasses.replace(cfg.clocking, pi_step_ui=0.0))
x3 = dataclasses.replace(x3, rx=dataclasses.replace(x3.rx, noise_rms_v=0.04),
                         sim=dataclasses.replace(x3.sim, n_symbols=2_000_000, engine="both"))
t0 = time.time()
res = run_link(x3)
mid_s, mid_t = res.stat[1], res.time[1]
ratio = mid_t.ber / mid_s.ber
print(f"crosstalk, x3 module at -14 dB, middle lane ({mid_s.extras['n_aggressors']} aggressors, "
      f"{1e3 * mid_s.extras['xtalk_rms_v']:.1f} mV RMS crosstalk): noise {1e3 * x3.rx.noise_rms_v:.1f} mV")
print(f"  statistical {mid_s.ber:.3e}   time {mid_t.ber:.3e} ({mid_t.n_errors} errors in {mid_t.error_bursts} bursts / "
      f"{mid_t.n_symbols:.1e}) "
      f"[{time.time() - t0:.0f}s]   ratio {ratio:.2f} -> {'within 0.5-2x' if 0.5 <= ratio <= 2.0 else 'OUTSIDE 0.5-2x'}; "
      f"edge lanes {res.consistency_ratios()[0]:.2f} / {res.consistency_ratios()[2]:.2f}")
results.append((mid_s, mid_t, ratio))

# 5. advanced package, 2 mm, CTLE, duty-cycle error
adv = load_config(CONFIGS / "advanced_32g_x64_spare.yaml")
adv = dataclasses.replace(adv, lanes=dataclasses.replace(adv.lanes, count=1, failed=(), repair="none", spare_count=0,
                                                         skew_sigma_ps=0.0),
                          clocking=dataclasses.replace(adv.clocking, data_path_rj_s=1e-12, clock_path_rj_s=1e-12, dcd_ui=0.06),
                          rx=dataclasses.replace(adv.rx, ctle=dataclasses.replace(adv.rx.ctle, enable=True, peak_db=3.0)),
                          sim=dataclasses.replace(adv.sim, stat_phase_points=cfg.sim.stat_phase_points))
adv = dataclasses.replace(adv, rx=dataclasses.replace(adv.rx, noise_rms_v=noise_for_ber(adv, 1e-5)))
results.append(point("advanced package, CTLE, 0.06 UI DCD", adv, 4_000_000))

ratios = [r for _, _, r in results]
print(f"\n{len(ratios)} points, ratios {min(ratios):.2f}..{max(ratios):.2f}"
      + (" -- all within 0.5-2x" if all(0.5 <= r <= 2.0 for r in ratios) else " -- SOME OUTSIDE 0.5-2x"))

plt = plt_or_none()
if plt is not None:

    from _common import OUT

    fig, ax = plt.subplots(figsize=(7, 4.2))
    names = ["local PLL", "quantised tracker", "wander", "crosstalk mid lane", "advanced + CTLE + DCD"]
    for k, ((s, td, r), name) in enumerate(zip(results, names)):
        lo, hi = td.ber_ci95
        ax.errorbar([k], [r], yerr=[[max(r - lo / s.ber, 0)], [hi / s.ber - r]], fmt="o", color=f"C{k}")
    ax.axhspan(0.5, 2.0, color="green", alpha=0.08)
    ax.set_yscale("log")
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=15, fontsize=8)
    ax.set_ylabel("time BER / statistical BER")
    ax.set_title("milestone-2 mechanisms: engine consistency")
    fig.tight_layout()
    path = OUT / "06_m2_consistency.png"
    fig.savefig(path, dpi=120)
    print(f"wrote {path}")
