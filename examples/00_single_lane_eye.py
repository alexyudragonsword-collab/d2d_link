"""Example 00: one lane of the milestone link, both engines, the eye and the budget.

Standard package, 32 GT/s, 25 mm, forwarded DDR clock from the shipped
pll_simulator profile (Markulic 2016 SSPLL), everything read from
``configs/standard_32g_x1.yaml``. The statistical engine gives the number
that matters -- the eye at BER 1e-27 against the survey targets -- and the
time engine draws the eye the sampler sees and confirms it counts no errors
where the statistics say there are none to count.

The jitter budget printed here is the point of the library: the PLL carries
~186 fs RMS in band, and the sampler sees none of it, because the forwarded
clock carries the same phase. What is left is the two paths' own jitter, the
receive tree, and the leak the tree's delay and bandwidth open.
"""

import time

import numpy as np

from _common import CONFIGS, OUT, fmt_target, plt_or_none
from d2d_link.clock.forwarded import ForwardedClock
from d2d_link.config import load_config
from d2d_link.engine import run_statistical, run_time
from d2d_link.channel import link_response

cfg = load_config(CONFIGS / "standard_32g_x1.yaml")
resp = link_response(cfg)
clock = ForwardedClock(cfg)
b = clock.budget()

print(f"link: {cfg.package.kind} package, {cfg.data_rate_gtps:g} GT/s, {cfg.channel.length_mm:g} mm, "
      f"{cfg.lanes.count} lane, forwarded clock {cfg.forwarded_clock_hz / 1e9:g} GHz DDR")
print(f"channel: insertion loss {resp.channel.insertion_loss_db(cfg.f_nyquist):.2f} dB at Nyquist "
      f"({cfg.f_nyquist / 1e9:g} GHz), main cursor {1e3 * resp.main_amplitude:.1f} mV of "
      f"{1e3 * cfg.tx.swing_vpp / 2:.0f} mV")
c, i_main = resp.cursors(0.0)
print("cursors at the peak [mV]: pre " + " ".join(f"{1e3 * x:.2f}" for x in c[max(0, i_main - 3):i_main])
      + f" | main {1e3 * c[i_main]:.2f} | post " + " ".join(f"{1e3 * x:.2f}" for x in c[i_main + 1:i_main + 5]))

print("\njitter budget at the sampler (RMS, closed form):")
print(f"  Tx PLL in band {b.f_lo_hz / 1e3:.1f} kHz .. {b.f_hi_hz / 1e9:.0f} GHz : {1e15 * clock.pll_rms_s():.1f} fs"
      f"  (what an independent clock would add)")
print(f"  common-mode leak (tree delay {cfg.clocking.tree_delay_ps:g} ps, bandwidth "
      f"{cfg.clocking.tree_bw_hz / 1e9:g} GHz)        : {1e15 * b.common_leak_s:.1f} fs")
print(f"  data path {1e15 * cfg.clocking.data_path_rj_s:.0f} fs after the {cfg.clocking.track_bw_hz / 1e6:g} MHz tracker"
      f"              : {1e15 * b.data_path_s:.1f} fs")
print(f"  clock path {1e15 * cfg.clocking.clock_path_rj_s:.0f} fs through tree and tracker"
      f"                : {1e15 * b.clock_path_s:.1f} fs")
print(f"  receive tree {1e15 * cfg.clocking.tree_rj_s:.0f} fs                                 "
      f"        : {1e15 * b.tree_s:.1f} fs")
print(f"  total residual                                            : {1e15 * b.total_s:.1f} fs "
      f"= {b.total_s / cfg.ui:.4f} UI")

t0 = time.time()
s = run_statistical(cfg, resp, clock=clock)
print(f"\nstatistical engine [{time.time() - t0:.1f}s]:")
print(f"  sampling phase {s.phase_ui:+.4f} UI from the pulse peak (eye centre), BER there {s.ber:.2e}")
print(f"  eye height at BER {s.target_ber:.0e}: {1e3 * s.eye_height_v:.1f} mV  vs target "
      f"{fmt_target(s, 'eye_height_mv', 'mV')} -> margin {s.eye_height_margin_mv:+.1f} mV")
print(f"  eye width  at BER {s.target_ber:.0e}: {s.eye_width_ui:.3f} UI  vs target "
      f"{fmt_target(s, 'eye_width_ui', 'UI')} -> margin {s.eye_width_margin_ui:+.3f} UI")
print(f"  BER target {s.target_ber:.0e} (source: {s.targets['ber'][1]}); "
      f"{s.extras['n_enumerated']} of {s.extras['n_cursors']} ISI cursors enumerated, the rest "
      f"{1e3 * s.extras['sigma_isi_rest_v']:.2f} mV RMS")
print(f"  verdict: {'PASS' if s.passes else 'FAIL'}")

t0 = time.time()
td = run_time(cfg, resp, phase_ui=s.phase_ui, clock=clock)
print(f"\ntime engine [{time.time() - t0:.1f}s]: {td.n_errors} errors in {td.n_symbols} symbols "
      f"(statistics predict {s.ber * td.n_symbols:.1e}); sampled eye opening {1e3 * td.eye_height_sampled_v:.1f} mV; "
      f"jitter the sampler saw {1e15 * td.jitter_rms_s:.1f} fs RMS")

plt = plt_or_none()
if plt is not None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    ax = axes[0]
    for tr in td.eye_traces:
        ax.plot(td.eye_time_ui, 1e3 * tr, color="C0", alpha=0.08, lw=0.8)
    ax.axvline(0.0, color="k", ls="--", lw=0.8)
    ax.set_xlabel("time from sampling instant [UI]")
    ax.set_ylabel("[mV]")
    ax.set_title("eye at the sampler (time engine)")
    ax = axes[1]
    ax.semilogy(s.bathtub_phase_ui, np.maximum(s.bathtub_ber, 1e-40))
    ax.axhline(s.target_ber, color="r", ls="--", lw=0.8, label=f"target {s.target_ber:.0e}")
    ax.axvline(s.phase_ui, color="k", ls=":", lw=0.8)
    ax.set_ylim(1e-40, 1)
    ax.set_xlabel("sampling phase [UI]")
    ax.set_ylabel("BER")
    ax.set_title("statistical bathtub")
    ax.legend()
    ax = axes[2]
    hi = td.samples[td.sample_bits > 0]
    lo = td.samples[td.sample_bits < 0]
    ax.hist(1e3 * hi, bins=80, alpha=0.7, label="+1")
    ax.hist(1e3 * lo, bins=80, alpha=0.7, label="-1")
    ax.set_xlabel("sampled value [mV]")
    ax.set_title("sampled values with noise")
    ax.legend()
    fig.tight_layout()
    path = OUT / "00_single_lane_eye.png"
    fig.savefig(path, dpi=120)
    print(f"wrote {path}")
