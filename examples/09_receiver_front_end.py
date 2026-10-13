"""Example 09: the receiver's own mechanisms -- front-end bandwidth, where the
noise is referred, what a CTLE costs, and how training centres the eye.

Every version before phase 7 gave the receiver an infinitely fast front end
and put its noise straight on the sampler: the clock tree had a bandwidth
(``clocking.tree_bw_hz``, on the clock's phase), the data edges did not.
Phase 7 adds ``rx.bw_hz`` (a first-order pole on the data path, flat when
unset -- the bundled configs still leave it unset: no spec number exists for
it, and it is the design's to give) and ``rx.noise_at``:

- ``sampler`` -- ``noise_rms_v`` is the RMS at the decision point, whatever
  the front end does (the earlier convention, still the default);
- ``input`` -- white noise at the front end's input, given as the RMS an
  ideal integrating receiver would see (PSD ``noise_rms_v^2 / f_N``). The
  sampler sees it through the front end and the CTLE:
  ``sigma = noise_rms_v sqrt(integral |H_fe H_ctle|^2 df / f_N)``.

Four readings of the single-lane standard-package link
(``configs/standard_32g_x1.yaml``), each a dataclass replace of the config:

1. **Bandwidth.** The eye against the front-end bandwidth, noise referred
   both ways: a narrower front end slows the pulse (less eye) and passes
   less noise (more eye); which wins is the number.
2. **CTLE cost.** At the package's reach the CTLE opens the eye in height;
   with the noise referred at the input its peaking also lets more noise
   through to the sampler -- the behavioural CTLE here has two poles and
   one zero, so it is itself a lowpass and a little peaking is free; the
   table shows where the cost starts.
3. **Training.** Link training centres the sampler between the eye's edges
   at the BER its eye monitor can see in its dwell, not at the 1e-27 the
   link is judged at (``rx.training_ber``). An asymmetric bathtub puts that
   midpoint off the target opening's; the lane spends eye width on the
   offset. Read on x1 and on the x5 coupled module's lanes.
4. **The time engine on the filtered noise.** With the noise at the input
   the waveform path really filters white noise through the front end and
   samples it: an independent check of the integral in (1).
"""

import dataclasses
import math

import numpy as np

from _common import CONFIGS, OUT, plt_or_none
from d2d_link.channel.model import noise_shaping_gain
from d2d_link.config import load_config
from d2d_link.engine import run_link, run_statistical, run_time

x1 = load_config(CONFIGS / "standard_32g_x1.yaml")
f_n = x1.f_nyquist


def with_rx(cfg, **kw):
    return dataclasses.replace(cfg, rx=dataclasses.replace(cfg.rx, **kw))


def with_ctle(cfg, peak_db):
    return with_rx(cfg, ctle=dataclasses.replace(cfg.rx.ctle, enable=peak_db > 0.0, peak_db=max(peak_db, 1e-9)))


# ------------------------------------------------------------- 1. bandwidth
print(f"x1 {x1.package.kind} package, {x1.channel.length_mm:g} mm, {x1.data_rate_gtps:g} GT/s, "
      f"noise {1e3 * x1.rx.noise_rms_v:g} mV, Tx pole {x1.tx_bw_hz / 1e9:g} GHz, clock tree {x1.clocking.tree_bw_hz / 1e9:g} GHz")
print(f"{'rx front end':>14s} {'main [mV]':>10s} {'noise at sampler: eye':>24s} {'noise at input: sigma_sampler / eye':>38s}")
sweep = {}
for bw in (None, 48e9, 32e9, 24e9, 16e9):
    a = run_statistical(with_rx(x1, bw_hz=bw))
    label = "flat" if bw is None else f"{bw / 1e9:g} GHz"
    if bw is None:
        b = None
        right = "(white noise through a flat front end has no RMS)"
    else:
        b = run_statistical(with_rx(x1, bw_hz=bw, noise_at="input"))
        right = f"{1e3 * b.sigma_noise_v:5.2f} mV  {1e3 * b.eye_height_v:6.1f} mV / {b.eye_width_ui:.3f} UI"
    sweep[label] = (a, b)
    print(f"{label:>14s} {1e3 * a.main_cursor_v:10.1f} {1e3 * a.eye_height_v:14.1f} mV / {a.eye_width_ui:.3f} UI {right:>38s}")
print("  the flat front end is the idealisation of every earlier version; the bundled configs keep it until a design gives a number\n")

# ------------------------------------------------------------- 2. CTLE cost
reach = dataclasses.replace(x1, channel=dataclasses.replace(x1.channel, length_mm=35.0))
reach = with_rx(reach, bw_hz=32e9)
print(f"CTLE at {reach.channel.length_mm:g} mm (the survey reach x 1.4 of example 02), front end {reach.rx.bw_hz / 1e9:g} GHz:")
print(f"{'CTLE peak':>10s} {'noise gain':>11s} {'at sampler: eye':>22s} {'at input: eye':>22s}")
ctle_rows = []
for pk in (0.0, 1.0, 2.0, 4.0, 6.0):
    c = with_ctle(reach, pk)
    a = run_statistical(c)
    b = run_statistical(with_rx(c, noise_at="input"))
    g = noise_shaping_gain(with_rx(c, noise_at="input"))
    ctle_rows.append((pk, g, a, b))
    print(f"{pk:9.0f}  {g:11.3f} {1e3 * a.eye_height_v:12.1f} mV / {a.eye_width_ui:.3f} {1e3 * b.eye_height_v:12.1f} mV / {b.eye_width_ui:.3f}")
best_s = max(ctle_rows, key=lambda r: r[2].eye_height_v)
best_i = max(ctle_rows, key=lambda r: r[3].eye_height_v)
print(f"  best peaking: {best_s[0]:g} dB with the noise at the sampler, {best_i[0]:g} dB with it at the input -- "
      "the CTLE's gain is bought with noise once the noise is where it physically enters\n")

# -------------------------------------------------------------- 3. training
print("training centres the eye at its own BER:")
print(f"{'link':>22s} {'training BER':>13s} {'centre [UI]':>12s} {'offset [UI]':>12s} {'eye [UI]':>9s} {'eye [mV]':>9s}")
ideal = sweep["flat"][0]
for tb in (None, 1e-3, 1e-6, 1e-9):
    r = ideal if tb is None else run_statistical(with_rx(x1, training_ber=tb))
    print(f"{'x1':>22s} {('target ' + f'{r.target_ber:.0e}') if tb is None else f'{tb:.0e}':>13s} {r.phase_ui:+12.5f} "
          f"{r.extras['centre_offset_ui']:+12.5f} {r.eye_width_ui:9.4f} {1e3 * r.eye_height_v:9.1f}")
x5 = load_config(CONFIGS / "standard_32g_x5_coupled.yaml")
res_t = run_link(x5)
res_e = run_link(with_rx(x5, training_ber=1e-3))
for a, b in zip(res_t.stat, res_e.stat):
    print(f"{'x5 coupled, lane ' + str(a.lane):>22s} {'1e-03':>13s} {b.phase_ui:+12.5f} {b.extras['centre_offset_ui']:+12.5f} "
          f"{b.eye_width_ui:9.4f} {1e3 * b.eye_height_v:9.1f}   (target-centred {a.eye_width_ui:.4f} UI)")
cost = max(zip(res_t.stat, res_e.stat), key=lambda ab: ab[0].eye_width_ui - ab[1].eye_width_ui)
print(f"  x5 module {'PASS' if res_t.passes else 'FAIL'} target-centred, {'PASS' if res_e.passes else 'FAIL'} trained at 1e-3 "
      f"(worst lane {res_t.worst.lane} -> {res_e.worst.lane}); x1's bathtub is nearly symmetric and training costs 0.002 UI, "
      f"the crosstalk-laden lanes pay up to {cost[0].eye_width_ui - cost[1].eye_width_ui:.3f} UI (lane {cost[0].lane})\n")

# ------------------------------------------------------- 4. the time engine
quiet = dataclasses.replace(x1.clocking, pll_profile=None, data_path_rj_s=0.0, clock_path_rj_s=0.0, tree_rj_s=0.0,
                            track_bw_hz=None)
chk = dataclasses.replace(x1, channel=dataclasses.replace(x1.channel, length_mm=1.0), clocking=quiet,
                          rx=dataclasses.replace(x1.rx, noise_rms_v=0.045, noise_at="input", bw_hz=24e9),
                          sim=dataclasses.replace(x1.sim, stat_phase_points=16))
s = run_statistical(chk)
t = run_time(chk, phase_ui=s.phase_ui)
sampled = t.samples - t.sample_bits * t.extras["main_cursor_v"]
noise_rms = math.sqrt(max(float(np.var(sampled)) - s.extras["sigma_isi_v"] ** 2, 0.0))
print(f"time engine on a {chk.channel.length_mm:g} mm line, {1e3 * chk.rx.noise_rms_v:g} mV at the input of a "
      f"{chk.rx.bw_hz / 1e9:g} GHz front end, {chk.sim.n_symbols} symbols:")
print(f"  statistics: sigma at the sampler {1e3 * s.sigma_noise_v:.2f} mV (gain {s.extras['noise_gain']:.3f}), BER {s.ber:.2e}")
print(f"  waveform path, white noise filtered through the front end: sampled noise RMS {1e3 * noise_rms:.2f} mV, "
      f"BER {t.ber:.2e} ({t.n_errors} errors), ratio {t.ber / s.ber:.2f}")
print(f"  the filtered noise is band-limited to osr / (2 UI) = {0.5 / chk.dt / 1e9:.0f} GHz; the integral runs to infinity "
      f"(the missing variance: {100 * (1 - (2 / math.pi) * math.atan(0.5 / chk.dt / chk.rx.bw_hz)):.1f} %)")

plt = plt_or_none()
if plt is not None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    labels = list(sweep)
    axes[0].plot(labels, [1e3 * sweep[k][0].eye_height_v for k in labels], "o-", label="noise at the sampler")
    axes[0].plot(labels[1:], [1e3 * sweep[k][1].eye_height_v for k in labels[1:]], "s-", label="noise at the input")
    axes[0].set_xlabel("front-end bandwidth")
    axes[0].set_ylabel("eye height [mV] at the target BER")
    axes[0].set_title(f"x1, {x1.channel.length_mm:g} mm")
    axes[0].legend()
    axes[1].plot([r[0] for r in ctle_rows], [1e3 * r[2].eye_height_v for r in ctle_rows], "o-", label="noise at the sampler")
    axes[1].plot([r[0] for r in ctle_rows], [1e3 * r[3].eye_height_v for r in ctle_rows], "s-", label="noise at the input")
    axes[1].set_xlabel("CTLE peaking [dB]")
    axes[1].set_ylabel("eye height [mV]")
    axes[1].set_title(f"{reach.channel.length_mm:g} mm, front end {reach.rx.bw_hz / 1e9:g} GHz")
    axes[1].legend()
    fig.tight_layout()
    png = OUT / "09_receiver_front_end.png"
    fig.savefig(png, dpi=120)
    print(f"wrote {png}")
