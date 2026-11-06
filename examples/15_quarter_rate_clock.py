"""Example 15: a quarter-rate forwarded clock (``clocking.scheme: forwarded_qdr``).

Until 0.15.0 the library knew one scheme: a half-rate (DDR) forwarded clock,
both edges sampling, so the receiver sees the clock's phase once per UI --
at the data's own rate. A quarter-rate clock runs at fs/4: its edges come
every 2 UI, and the receiver's four sampling phases (0 / 90 / 180 / 270
degrees) come from a 4-phase generator between them. Two things change in
this model, both ``source: model`` (no spec text is available):

- **the clock's phase is seen at its edges only, and interpolated between
  them.** On the UI grid: every other sample kept, the rest the mean of
  their neighbours. A phase tone at f comes out as cos^2(pi f / fs) of
  itself (1/2 at fs/4, 0 at fs/2) -- Tx PLL noise up there reaches the
  data but no longer the sampler, so near fs/2 the ~1 UI tree no longer
  turns the common-mode leak |1 - G|^2 to ~3 (example 10) -- and as much
  of its image at fs/2 - f, clock-path noise the data does not share
  (``JitterBudget.edge_alias_s``, 0.15.1; 0.15.0 had the continuous-time
  sinc^2 and no image, and read x1's residual 292.5 fs instead of 334).
- **four sampling phases, not two.** The duty-cycle error still splits
  rising from falling edges; a quadrature skew q of the 4-phase generator
  (``clocking.qdr_quadrature_ui``) splits the 0/180 pair from the 90/270
  pair. The lane samples at (-dcd - q, -dcd + q, dcd - q, dcd + q) / 2,
  each a quarter of the time: a bounded box like the PI step, so at
  1e-27 it costs about its width.

Every point is a dataclass replace of a bundled config.
"""

import dataclasses

from _common import CONFIGS
from d2d_link.clock.forwarded import ForwardedClock
from d2d_link.config import load_config
from d2d_link.engine import run_link

R = dataclasses.replace


def schemed(cfg, scheme, q=0.0):
    return R(cfg, clocking=R(cfg.clocking, scheme=scheme, qdr_quadrature_ui=q))


print(f"{'config':<26s} {'scheme':<14s} {'Tx leak [fs]':>12s} {'edge alias [fs]':>15s} {'residual [fs]':>13s} {'eye [UI]':>9s} "
      f"{'eye [mV]':>9s} {'link':>5s}")
for name in ("standard_32g_x1", "standard_32g_x16_module"):
    cfg = load_config(CONFIGS / f"{name}.yaml")
    for scheme in ("forwarded_ddr", "forwarded_qdr"):
        c = schemed(cfg, scheme)
        b = ForwardedClock(c).budget()
        r = run_link(c)
        print(f"{name:<26s} {scheme:<14s} {1e15 * b.common_leak_s:12.1f} {1e15 * b.edge_alias_s:15.1f} {1e15 * b.total_s:13.1f} "
              f"{r.worst.eye_width_ui:9.4f} "
              f"{1e3 * r.worst.eye_height_v:9.1f} {'PASS' if r.passes else 'FAIL':>5s}")
print("  x1 has no local PLL: the quarter-rate edges stop the tree's phase flip near fs/2 from doubling the Tx floor,"
      " but fold the clock path's own noise from fs/2 - f back in; the x16 module's 1 MHz local PLL had already cut"
      " the clock off up there and filters the folded part too\n")

x1 = load_config(CONFIGS / "standard_32g_x1.yaml")
print("quadrature skew of the 4-phase generator (x1, forwarded_qdr):")
print(f"{'q [UI]':>7s} {'offsets [UI]':>32s} {'eye [UI]':>9s} {'cost [UI]':>10s} {'link':>5s}")
base = None
for q in (0.0, 0.01, 0.02, 0.04, 0.06):
    c = schemed(x1, "forwarded_qdr", q)
    r = run_link(c)
    base = r.worst.eye_width_ui if base is None else base
    offs = ", ".join(f"{o:+.3f}" for o in ForwardedClock(c).sampling_offsets_ui())
    print(f"{q:7.2f} {offs:>32s} {r.worst.eye_width_ui:9.4f} {base - r.worst.eye_width_ui:10.4f} {'PASS' if r.passes else 'FAIL':>5s}")
print("  a box of total width q costs about q of eye width at the target BER (the phases are bounded, not Gaussian)")
