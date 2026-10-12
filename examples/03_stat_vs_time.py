"""Example 03: statistical / time-domain consistency at a BER the time engine can count.

A raw BER of 1e-27 is the statistical engine's alone (invariant #3). Its
credibility comes from here: the same link, its noise raised until the
statistics predict about 1e-6, then run through the time engine for enough
symbols to count errors, and the ratio reported. The acceptance is 0.5-2x.
Two operating points: noise-dominated (the receiver's noise raised) and
jitter-dominated (the paths' jitter raised with the tracker off, so the
sampler, not the slicer, makes the errors). A third, mixed, point at
~1e-5 checks the two mechanisms combine as the engine assumes.
"""

import dataclasses
import time

from _common import CONFIGS, OUT, plt_or_none
from d2d_link.config import load_config
from d2d_link.engine import run_time
from d2d_link.engine.statistical import StatisticalEngine

cfg = load_config(CONFIGS / "standard_32g_x1.yaml")


def noise_for_ber(cfg, target: float) -> float:
    """The sampler noise at which the statistical engine predicts ``target``
    at the eye centre (bisection on one engine: the ISI models do not depend
    on the noise)."""
    eng = StatisticalEngine(cfg)
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


def jitter_for_ber(cfg, target: float) -> float:
    """The per-path white jitter (data and clock paths alike, tracker off) at
    which the statistics predict ``target`` with the receiver kept quiet. The
    jitter changes the quadrature, so the engine is rebuilt per step on a
    coarse bathtub."""
    coarse = dataclasses.replace(cfg, sim=dataclasses.replace(cfg.sim, stat_phase_points=16))
    lo, hi = 0.5e-12, 6e-12
    for _ in range(14):
        mid = (lo * hi) ** 0.5
        c = dataclasses.replace(coarse, clocking=dataclasses.replace(
            coarse.clocking, data_path_rj_s=mid, clock_path_rj_s=mid, track_bw_hz=None))
        if StatisticalEngine(c).run().ber > target:
            hi = mid
        else:
            lo = mid
    return (lo * hi) ** 0.5


points = []
for name, target, n_symbols in (("noise-dominated", 1e-6, 20_000_000),
                                ("jitter-dominated", 1e-6, 20_000_000),
                                ("mixed", 1e-5, 2_000_000)):
    if name == "noise-dominated":
        c = cfg
        noise = noise_for_ber(c, target)
    elif name == "jitter-dominated":
        rj = jitter_for_ber(cfg, target)
        c = dataclasses.replace(cfg, clocking=dataclasses.replace(cfg.clocking, data_path_rj_s=rj,
                                                                  clock_path_rj_s=rj, track_bw_hz=None))
        noise = cfg.rx.noise_rms_v           # the receiver stays quiet: errors come from timing
    else:
        c = dataclasses.replace(cfg, clocking=dataclasses.replace(cfg.clocking, data_path_rj_s=1.5e-12,
                                                                  clock_path_rj_s=1.5e-12, track_bw_hz=None))
        noise = noise_for_ber(c, target)
    c = dataclasses.replace(c, rx=dataclasses.replace(c.rx, noise_rms_v=noise),
                            sim=dataclasses.replace(c.sim, n_symbols=n_symbols))
    t0 = time.time()
    s = StatisticalEngine(c).run()
    t_stat = time.time() - t0
    t0 = time.time()
    td = run_time(c, phase_ui=s.phase_ui)
    t_time = time.time() - t0
    lo, hi = td.ber_ci95
    ratio = td.ber / s.ber if s.ber > 0 else float("inf")
    points.append((name, s, td, ratio))
    print(f"{name}: noise {1e3 * noise:.2f} mV, jitter {1e15 * s.sigma_jitter_s:.0f} fs "
          f"({s.sigma_jitter_s / c.ui:.3f} UI), phase {s.phase_ui:+.4f} UI")
    print(f"  statistical BER {s.ber:.3e} [{t_stat:.1f}s]   time BER {td.ber:.3e} "
          f"({td.n_errors} errors / {td.n_symbols:.1e} symbols, 95% {lo:.1e}..{hi:.1e}) [{t_time:.0f}s]")
    print(f"  ratio time / statistical = {ratio:.2f}  -> {'within 0.5-2x' if 0.5 <= ratio <= 2.0 else 'OUTSIDE 0.5-2x'}")

plt = plt_or_none()
if plt is not None:
    import numpy as np

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for k, (name, s, td, ratio) in enumerate(points):
        ax.semilogy(s.bathtub_phase_ui, np.maximum(s.bathtub_ber, 1e-30), color=f"C{k}", label=f"{name}: statistical")
        lo, hi = td.ber_ci95
        ax.errorbar([td.phase_ui], [max(td.ber, 1e-30)], yerr=[[max(td.ber - lo, 0)], [hi - td.ber]],
                    fmt="o", color=f"C{k}", label=f"{name}: time ({td.n_errors} errors)")
    ax.set_ylim(1e-12, 1)
    ax.set_xlabel("sampling phase [UI]")
    ax.set_ylabel("BER")
    ax.set_title("statistical bathtub vs time-engine count")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=7)
    fig.tight_layout()
    path = OUT / "03_stat_vs_time.png"
    fig.savefig(path, dpi=120)
    print(f"wrote {path}")
