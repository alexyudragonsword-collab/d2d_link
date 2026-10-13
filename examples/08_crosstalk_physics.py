"""Example 08: what the crosstalk estimate rests on -- routing, direction, and a file.

Three views of the same x5 standard-package module at 32 GT/s
(``configs/standard_32g_x5_coupled.yaml``), each read from the config and a
dataclass replace, never a loose number:

1. **Routing.** The far-end crosstalk of coupled lines needs the even and odd
   modes to travel at different speeds, which a microstrip's inhomogeneous
   dielectric gives and a stripline's homogeneous one does not: the same
   geometry routed as a stripline has no first-order FEXT, and its line is
   slower (eps_eff = eps_r). The module's verdict flips with the routing --
   which is the point: the -18.6 dB that fails the 32 GT/s standard package
   is a microstrip model estimate.
2. **Direction.** Lanes at the module's edge sit next to the return module's
   lanes, which transmit the other way: their near-end crosstalk arrives at
   this receiver's die without crossing the lossy line, as a pulse pair
   2 tau_c apart with the backward coefficient K_b = kappa / 4.
3. **A file.** A single-ended 2N-port Touchstone extraction carries its own
   coupling terms. Lacking a real one (ROADMAP P1 #2), a synthetic 3-lane
   file is written here from the analytic line's own transfer and the
   analytic FEXT shape at -20 dB, read back through ``channel.xtalk:
   touchstone`` and compared with the analytic path on the same numbers:
   the two must agree, which exercises the reader end to end. The amplitude
   stays a model estimate until a real extraction replaces the file.
"""

import dataclasses

import numpy as np

from _common import CONFIGS, OUT, plt_or_none
from d2d_link.channel import ChannelModel, link_response
from d2d_link.channel.coupled import describe
from d2d_link.config import load_config
from d2d_link.engine import run_link

module = load_config(CONFIGS / "standard_32g_x5_coupled.yaml")
mid = module.lanes.count // 2

# ---------------------------------------------------------------- 1. routing
print(f"x{module.lanes.count} module, {module.package.kind} package, {module.channel.length_mm:g} mm, "
      f"{module.data_rate_gtps:g} GT/s, coupled-line crosstalk estimate")
print(f"{'routing':>10s} {'eps_eff':>8s} {'FEXT adj [dB]':>14s} {'delay [ps]':>11s} {'mid eye [mV]':>13s} "
      f"{'mid eye [UI]':>13s} {'worst lane':>10s} {'verdict':>8s}")
routing = {}
for name in ("microstrip", "stripline"):
    cfg = dataclasses.replace(module, channel=dataclasses.replace(module.channel, routing=name))
    x = describe(cfg)
    res = run_link(cfg)
    m = res.stat[mid]
    routing[name] = (x, res)
    fext = f"{x['fext_adjacent_db']:.1f}" if x["fext_adjacent_db"] > -200 else "none (1st order)"
    print(f"{name:>10s} {x['eps_eff']:8.2f} {fext:>14s} {x['coupled_delay_ps']:11.1f} {1e3 * m.eye_height_v:13.1f} "
          f"{m.eye_width_ui:13.3f} {res.worst.lane:10d} {'PASS' if res.passes else 'FAIL':>8s}")
print("  the 32 GT/s verdict on the standard package is a routing assumption: a stripline of the same geometry passes")

# -------------------------------------------------------------- 2. direction
edges = (0, module.lanes.count - 1)
nx = dataclasses.replace(module, channel=dataclasses.replace(module.channel, xtalk_next="coupled"),
                         lanes=dataclasses.replace(module.lanes, reverse_adjacent=edges))
xn = describe(nx)
res_n = run_link(nx)
res_0 = routing["microstrip"][1]
pn = link_response(nx).xtalk_pulses["next"].y
print(f"\nnear-end crosstalk from the return module on edge lanes {list(edges)}: K_b = kappa/4 = {xn['next_db']:.1f} dB, "
      f"two lobes {2 * xn['coupled_delay_ps']:.0f} ps = {2e-12 * xn['coupled_delay_ps'] / nx.ui:.1f} UI apart, "
      f"peak {1e3 * np.max(np.abs(pn)):.1f} mV of {1e3 * link_response(nx).main_amplitude:.1f} mV main")
print(f"{'lane':>5s} {'aggressors':>10s} {'xtalk [mV]':>10s} {'eye [mV] off/on':>16s} {'eye [UI] off/on':>16s}")
for a, b in zip(res_0.stat, res_n.stat):
    print(f"{a.lane:5d} {a.extras['n_aggressors']:>4d} -> {b.extras['n_aggressors']:<3d} "
          f"{1e3 * a.extras['xtalk_rms_v']:4.1f} -> {1e3 * b.extras['xtalk_rms_v']:<4.1f} "
          f"{1e3 * a.eye_height_v:7.1f} / {1e3 * b.eye_height_v:<6.1f} {a.eye_width_ui:7.3f} / {b.eye_width_ui:<6.3f}")
print(f"  module {'PASS' if res_n.passes else 'FAIL'} with NEXT (worst lane {res_n.worst.lane}); "
      f"the reverse lane's symbols sit {nx.lanes.reverse_phase_ui:g} UI off this module's sampling instant (a config choice)")

# ----------------------------------------------------------------- 3. a file
try:
    import skrf
except ImportError:
    skrf = None
if skrf is not None:
    f = ChannelModel.grid(module)[1:]
    thru = ChannelModel.from_config(module).H[1:]    # the analytic 25 mm line itself, as the file's through terms
    level = 10 ** (-20.0 / 20.0)                     # the synthetic file's coupling: -20 dB at Nyquist, FEXT shape
    kx = level * np.sqrt(2.0) * (1j * f / module.f_nyquist) / (1 + 1j * f / module.f_nyquist)
    n = 3
    s = np.zeros((f.size, 2 * n, 2 * n), dtype=complex)
    for i in range(n):
        s[:, n + i, i] = s[:, i, n + i] = thru
        for j in range(n):
            if abs(i - j) == 1:
                s[:, n + i, j] = s[:, j, n + i] = kx * thru
            elif abs(i - j) == 2:
                s[:, n + i, j] = s[:, j, n + i] = 0.25 * kx * thru
    path = OUT / "08_synthetic_3lane"
    skrf.Network(f=f, s=s, z0=50.0, f_unit="Hz").write_touchstone(str(path), form="ri")
    file_cfg = dataclasses.replace(module, channel=dataclasses.replace(
        module.channel, kind="touchstone", file=str(path) + ".s6p", touchstone_mode="single_ended", xtalk="touchstone",
        coupled_length_mm=module.channel.length_mm),
        lanes=dataclasses.replace(module.lanes, count=n))
    analytic_cfg = dataclasses.replace(module, channel=dataclasses.replace(module.channel, xtalk="fext", xtalk_adjacent_db=-20.0,
                                                                              xtalk_second_db=-32.0),
                                       lanes=dataclasses.replace(module.lanes, count=n))
    res_f, res_a = run_link(file_cfg), run_link(analytic_cfg)
    ch = ChannelModel.from_config(file_cfg)
    k = int(np.argmin(np.abs(ch.f - module.f_nyquist)))
    print(f"\nsynthetic single-ended 6-port file {path.name}.s6p (the analytic 25 mm line as 3 lanes, FEXT -20 dB / -32 dB at Nyquist):")
    il_analytic = ChannelModel.from_config(module).insertion_loss_db(module.f_nyquist)
    print(f"  read back for lane {file_cfg.channel.lane}: |H| {20 * np.log10(abs(ch.H[k])):.2f} dB at Nyquist "
          f"(analytic {il_analytic:.2f} dB), "
          f"coupling from the neighbour {20 * np.log10(abs(ch.xtalk_H[1][k])):.1f} dB, second {20 * np.log10(abs(ch.xtalk_H[2][k])):.1f} dB")
    print(f"{'lane':>5s} {'file: eye [mV] / [UI]':>22s} {'analytic -20 dB: eye [mV] / [UI]':>32s}")
    for a, b in zip(res_f.stat, res_a.stat):
        print(f"{a.lane:5d} {1e3 * a.eye_height_v:12.1f} / {a.eye_width_ui:<6.3f} {1e3 * b.eye_height_v:22.1f} / {b.eye_width_ui:<6.3f}")
    worst = max(abs(a.eye_height_v - b.eye_height_v) for a, b in zip(res_f.stat, res_a.stat))
    print(f"  file path and analytic path agree to {1e3 * worst:.2f} mV on a file built from the analytic model: the reader is exercised "
          "end to end; a real package extraction would replace both numbers -- the reader is ready, the data is not")
else:
    print("\nscikit-rf not installed: the single-ended Touchstone part is skipped")

plt = plt_or_none()
if plt is not None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    r = link_response(nx)
    t = np.arange(pn.size) / r.osr
    axes[0].plot(t, 1e3 * r.xtalk_pulses[1].y, label="FEXT, nearest lane (microstrip)")
    axes[0].plot(t, 1e3 * pn, label="NEXT, reverse lane")
    axes[0].set_xlim(0, 20)
    axes[0].set_xlabel("time [UI]")
    axes[0].set_ylabel("[mV]")
    axes[0].set_title("crosstalk pulses at the sampler")
    axes[0].legend()
    for name, (x, res) in routing.items():
        axes[1].bar(name, res.stat[mid].eye_width_ui)
    axes[1].bar("microstrip + NEXT (edge)", res_n.stat[0].eye_width_ui)
    axes[1].axhline(res_0.targets["eye_width_ui"][0], color="r", ls="--", lw=0.8, label="target")
    axes[1].set_ylabel("eye width [UI] at the target BER")
    axes[1].set_title("the verdict and its assumptions")
    axes[1].legend()
    fig.tight_layout()
    png = OUT / "08_crosstalk_physics.png"
    fig.savefig(png, dpi=120)
    print(f"wrote {png}")
