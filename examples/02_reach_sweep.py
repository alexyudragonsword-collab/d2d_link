"""Example 02: channel length sweep to the reach limit of the standard package.

The milestone link with its analytic lossy line swept from 5 mm out past the
survey reach. For every length the statistical engine reports the insertion
loss, the eye height and width at BER 1e-27 and the BER at the eye centre;
the reach is the last length at which the eye still clears both survey
targets and the BER target. It is compared with the survey figure for the
package (``standard.reach_mm``, source: survey) -- a factor of two either way
means the model or the targets are wrong, and cairn/LOG.md must say which.
"""

import dataclasses

import numpy as np

from _common import CONFIGS, OUT, plt_or_none
from d2d_link.config import load_config
from d2d_link.engine import run_statistical
from d2d_link.spec import survey

cfg = load_config(CONFIGS / "standard_32g_x1.yaml")
lengths = np.arange(5.0, 65.0, 5.0)
reach = survey("reach_mm", cfg.package.kind)

print(f"{cfg.package.kind} package, {cfg.data_rate_gtps:g} GT/s; survey reach {reach.value:g} {reach.unit} "
      f"(source: {reach.source}; {reach.cite})")
print(f"{'length [mm]':>11s} {'IL@Nyq [dB]':>12s} {'eye height [mV]':>16s} {'eye width [UI]':>15s} "
      f"{'BER at centre':>14s} {'margin EH [mV]':>15s} {'pass':>5s}")
last_pass = None
rows = []
for L in lengths:
    c = dataclasses.replace(cfg, channel=dataclasses.replace(cfg.channel, length_mm=float(L)))
    s = run_statistical(c)
    ok = s.passes
    if ok:
        last_pass = L
    rows.append((L, s.extras["insertion_loss_nyquist_db"], s.eye_height_v, s.eye_width_ui, s.ber, ok))
    print(f"{L:11.0f} {s.extras['insertion_loss_nyquist_db']:12.2f} {1e3 * s.eye_height_v:16.1f} "
          f"{s.eye_width_ui:15.3f} {s.ber:14.2e} {s.eye_height_margin_mv:15.1f} {'yes' if ok else 'no':>5s}")

targets = run_statistical(cfg).targets
eh_t, ber_t = targets["eye_height_mv"], targets["ber"]
if last_pass is None:
    print("\nno length passes")
else:
    ratio = last_pass / reach.value
    print(f"\nmodel reach: {last_pass:.0f} mm is the last length that clears eye height "
          f"{eh_t[0]:g} mV (source: {eh_t[1]}), eye width and BER {ber_t[0]:.0e} (source: {ber_t[1]}); "
          f"survey reach {reach.value:g} mm -> ratio {ratio:.2f}x"
          + ("  (within 2x)" if 0.5 <= ratio <= 2.0 else "  (MORE THAN 2x APART: see cairn/LOG.md)"))

plt = plt_or_none()
if plt is not None:
    fig, ax1 = plt.subplots(figsize=(7, 4.2))
    ax1.plot([r[0] for r in rows], [1e3 * r[2] for r in rows], "o-", label="eye height at 1e-27 [mV]")
    ax1.axhline(eh_t[0], color="C0", ls="--", lw=0.8, label=f"target {eh_t[0]:g} mV (source: {eh_t[1]})")
    ax1.axvline(reach.value, color="gray", ls=":", lw=0.8, label=f"survey reach {reach.value:g} mm")
    ax1.set_xlabel("length [mm]")
    ax1.set_ylabel("eye height [mV]")
    ax2 = ax1.twinx()
    ax2.plot([r[0] for r in rows], [r[3] for r in rows], "s-", color="C1", label="eye width [UI]")
    ax2.set_ylabel("eye width [UI]")
    ax1.legend(loc="upper right", fontsize=8)
    ax2.legend(loc="lower left", fontsize=8)
    ax1.set_title("standard package, 32 GT/s: reach sweep")
    fig.tight_layout()
    path = OUT / "02_reach_sweep.png"
    fig.savefig(path, dpi=120)
    print(f"wrote {path}")
