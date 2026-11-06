"""Channel and pulse response."""

import dataclasses

import numpy as np
import pytest

from d2d_link.channel import ChannelModel, link_response
from d2d_link.channel.model import ctle_response
from d2d_link.config import ChannelConfig, CtleConfig, LinkConfig, RxConfig, SimConfig, TxConfig


def _lossless(length_mm=25.0):
    return LinkConfig(channel=ChannelConfig(length_mm=length_mm, rdc_ohm_m=0.0, r_skin=0.0,
                                            loss_tangent=0.0, g_s_m=0.0, l_h_m=2.5e-7, c_f_m=1.0e-10))


def test_lossless_matched_line_is_unity():
    ch = ChannelModel.from_config(_lossless())
    assert np.allclose(np.abs(ch.H), 1.0, atol=1e-9)
    assert ch.insertion_loss_db(16e9) == pytest.approx(0.0, abs=1e-6)


def test_loss_grows_with_length_and_frequency():
    il = [ChannelModel.from_config(LinkConfig(channel=ChannelConfig(length_mm=L))).insertion_loss_db(16e9)
          for L in (5.0, 15.0, 25.0)]
    assert il[0] > il[1] > il[2]
    ch = ChannelModel.from_config(LinkConfig())
    assert ch.insertion_loss_db(16e9) < ch.insertion_loss_db(4e9) < 0.0
    # the standard-package preset at the survey reach: a few dB at Nyquist
    assert -6.0 < il[2] < -1.5


def test_pulse_amplitude_and_cursor_sum():
    cfg = LinkConfig()
    r = link_response(cfg)
    c, i_main = r.cursors(0.0)
    assert c[i_main] == pytest.approx(r.main_amplitude)
    # the cursors sum to the DC response times the symbol amplitude
    dc = abs(r.channel.H[0]) * 0.5 * cfg.tx.swing_vpp
    assert np.sum(c) == pytest.approx(dc, rel=0.02)
    assert r.main_amplitude < 0.5 * cfg.tx.swing_vpp
    assert r.cursors(0.5)[0].size >= 3


def test_lossless_pulse_is_the_symbol_amplitude():
    # a brick-wall band edge rings (Gibbs), so the peak overshoots a little;
    # the cursors still sum to the symbol amplitude exactly
    r = link_response(_lossless(5.0))
    c, _ = r.cursors(0.0)
    assert np.sum(c) == pytest.approx(0.5 * 0.4, rel=0.01)   # sinc tails beyond +-64 UI
    assert r.main_amplitude == pytest.approx(0.5 * 0.4, rel=0.15)


def test_ctle_unity_dc_and_peaking():
    cfg = LinkConfig(rx=RxConfig(ctle=CtleConfig(enable=True, peak_db=4.0)))
    f = np.array([0.0, cfg.f_nyquist])
    h = np.abs(ctle_response(cfg, f))
    assert h[0] == pytest.approx(1.0)
    assert 1.0 < 20 * np.log10(h[1]) < 4.0      # peak_db is the asymptote, not the boost at fp1
    assert np.all(ctle_response(LinkConfig(), f) == 1.0)


def test_grid_matches_waveform_step():
    cfg = LinkConfig()
    r = link_response(cfg)
    assert r.pulse.dt == pytest.approx(cfg.dt, rel=1e-9)


def test_touchstone_path_through_vendored_reader(tmp_path):
    skrf = pytest.importorskip("skrf")
    # a lossless matched differential line written as a 4-port single-ended file
    cfg = _lossless(10.0)
    f = ChannelModel.grid(cfg)[1:]
    z0 = 50.0
    beta = 2 * np.pi * f * np.sqrt(2.5e-7 * 1.0e-10)
    s = np.zeros((f.size, 4, 4), dtype=complex)
    thru = np.exp(-1j * beta * 0.010)
    s[:, 0, 1] = s[:, 1, 0] = thru     # +A -> +B
    s[:, 2, 3] = s[:, 3, 2] = thru     # -A -> -B
    ntwk = skrf.Network(f=f, s=s, z0=z0, f_unit="Hz")
    path = tmp_path / "line.s4p"
    ntwk.write_touchstone(str(path.with_suffix("")), form="ri")
    cfg2 = LinkConfig(channel=ChannelConfig(kind="touchstone", file=str(path), renumber=False))
    ch = ChannelModel.from_config(cfg2)
    assert np.allclose(np.abs(ch.H[1:-1]), 1.0, atol=0.02)


def test_single_ended_multiport_touchstone_carries_its_own_crosstalk(tmp_path):
    """A 2N-port single-ended file (ports 1..N near ends, N+1..2N far ends):
    the lane's through path reads 1 on a lossless matched line and the
    neighbours' coupling terms become the crosstalk pulses, reciprocal
    between lanes, with no behavioural shape imposed."""
    skrf = pytest.importorskip("skrf")
    from d2d_link.config import LaneConfig

    cfg = LinkConfig()
    f = ChannelModel.grid(cfg)[1:]
    beta = 2 * np.pi * f * np.sqrt(2.656e-7 * 1.063e-10)
    thru = np.exp(-1j * beta * 0.025)
    kx = 0.1 * (1j * f / cfg.f_nyquist) / (1 + 1j * f / cfg.f_nyquist)      # -20 dB at Nyquist, FEXT-shaped
    n = 3
    s = np.zeros((f.size, 2 * n, 2 * n), dtype=complex)
    for i in range(n):
        s[:, n + i, i] = s[:, i, n + i] = thru
        for j in range(n):
            if abs(i - j) == 1:
                s[:, n + i, j] = s[:, j, n + i] = kx * thru
            elif abs(i - j) == 2:
                s[:, n + i, j] = s[:, j, n + i] = 0.3 * kx * thru
    path = tmp_path / "lanes"
    skrf.Network(f=f, s=s, z0=50.0, f_unit="Hz").write_touchstone(str(path), form="ri")
    file = str(path) + ".s6p"
    mid = LinkConfig(channel=ChannelConfig(kind="touchstone", file=file, touchstone_mode="single_ended", lane=1,
                                           xtalk="touchstone"), lanes=LaneConfig(count=3))
    ch = ChannelModel.from_config(mid)
    k = int(np.argmin(np.abs(ch.f - cfg.f_nyquist)))
    assert np.allclose(np.abs(ch.H[1:-1]), 1.0, atol=0.02) and sorted(ch.xtalk_H) == [1]
    assert abs(ch.xtalk_H[1][k]) == pytest.approx(0.1 / np.sqrt(2.0), rel=0.02)          # |kx| at Nyquist
    edge = ChannelModel.from_config(dataclasses.replace(mid, channel=dataclasses.replace(mid.channel, lane=0)))
    assert sorted(edge.xtalk_H) == [1, 2] and abs(edge.xtalk_H[2][k]) == pytest.approx(0.03 / np.sqrt(2.0), rel=0.02)
    assert np.allclose(edge.xtalk_H[1], ch.xtalk_H[1])                                     # reciprocal coupling
    r = link_response(mid)
    assert sorted(r.xtalk_pulses) == [1] and 0.03 < np.max(np.abs(r.xtalk_pulses[1].y)) / r.main_amplitude < 0.1
    with pytest.raises(ValueError, match="single-ended"):
        ChannelConfig(kind="touchstone", file=file, xtalk="touchstone")
    with pytest.raises(ValueError, match="2N"):
        ChannelModel.from_touchstone_single_ended(file, ChannelModel.grid(cfg), 50.0, 50.0, 0, n_lanes=4)


def test_touchstone_channels_have_no_dc_notch(tmp_path):
    """The file has no DC point and the interpolation fills transmission
    outside its band with 0: without fill_dc the through path read H(0) = 0,
    a notch that hung a long negative tail on the pulse (a 182 mV eye read
    60 mV in example 08's first draft). Both readers carry the lowest in-band
    magnitude to DC; the pulse's cursor sum then matches the lossy line's."""
    skrf = pytest.importorskip("skrf")
    from d2d_link.channel.model import fill_dc
    from d2d_link.config import LaneConfig

    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0))
    ana = ChannelModel.from_config(cfg)
    f = ana.f[1:]
    n = 2
    s = np.zeros((f.size, 2 * n, 2 * n), dtype=complex)
    for i in range(n):
        s[:, n + i, i] = s[:, i, n + i] = ana.H[1:]
    path = tmp_path / "lossy"
    skrf.Network(f=f, s=s, z0=50.0, f_unit="Hz").write_touchstone(str(path), form="ri")
    se = LinkConfig(channel=ChannelConfig(kind="touchstone", file=str(path) + ".s4p", touchstone_mode="single_ended",
                                          coupled_length_mm=25.0), lanes=LaneConfig(count=2))
    ch = ChannelModel.from_config(se)
    assert abs(ch.H[0]) == pytest.approx(abs(ana.H[0]), rel=2e-3) and ch.H[0].imag == 0.0   # sqrt(f) extrapolation to DC
    assert np.allclose(np.abs(ch.H[1:-1]), np.abs(ana.H[1:-1]), rtol=1e-3)
    r_file, r_ana = link_response(se), link_response(cfg)
    assert np.sum(r_file.cursors(0.0)[0]) == pytest.approx(np.sum(r_ana.cursors(0.0)[0]), rel=2e-3)
    assert r_file.main_amplitude == pytest.approx(r_ana.main_amplitude, rel=2e-3)
    # the differential reader goes through the same fill (its port order is 1+, 2+, 1-, 2-: through = 0 -> 1, 2 -> 3)
    sd = np.zeros_like(s)
    sd[:, 1, 0] = sd[:, 0, 1] = sd[:, 3, 2] = sd[:, 2, 3] = ana.H[1:]
    skrf.Network(f=f, s=sd, z0=50.0, f_unit="Hz").write_touchstone(str(tmp_path / "lossy_diff"), form="ri")
    diff = ChannelModel.from_config(LinkConfig(channel=ChannelConfig(kind="touchstone", file=str(tmp_path / "lossy_diff.s4p"),
                                                                     renumber=False)))
    assert diff.H[0] != 0.0 and abs(diff.H[0]) == pytest.approx(abs(ana.H[0]), rel=2e-3)
    h = np.array([0.0, 0.5 + 0.1j, 0.4]); assert abs(fill_dc(h, np.array([0.0, 1.0, 2.0]))[0]) >= abs(0.5 + 0.1j)
    assert fill_dc(np.array([0.9, 0.5, 0.4]), np.array([0.0, 1.0, 2.0]))[0] == 0.9           # a file with DC is left alone
    assert fill_dc(np.array([0.0, 0.5, 0.6]), np.array([0.0, 1.0, 2.0]))[0] == 0.5           # rising: no extrapolation, the lowest point



def test_analytic_line_is_causal():
    """The vendored RLGC gives R = R_dc + r_skin sqrt(f) with a constant L;
    the skin effect's surface impedance is (1 + j) r_skin sqrt(f), so an
    internal inductance r_skin / (2 pi sqrt(f)) belongs with it. Without it
    H(f) violates causality and the pulse carries energy before the line's
    LC delay -- 6.5 % of the main cursor at the arrival, 2 % a whole UI
    before it, on the 25 mm standard line; no earlier probe looked at it
    (second health check, 2026-11-02). The insertion loss hardly moves; the
    post-cursor dispersion does."""
    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0), tx=TxConfig(bw_hz=60e9))     # the x1 config's driver
    old = dataclasses.replace(cfg, channel=dataclasses.replace(cfg.channel, skin_inductance=False))
    p = cfg.rlgc()
    tau = cfg.channel.length_mm * 1e-3 * np.sqrt(p["l_h_m"] * p["c_f_m"])      # the line's LC delay

    def pre_arrival(c):
        r = link_response(c)
        n = int(tau / c.dt) - c.sim.osr                                           # one UI before the LC arrival
        return float(np.max(np.abs(r.pulse.y[:n]))) / r.main_amplitude

    assert pre_arrival(cfg) < 0.005          # 0.3 % (the band edge's Gibbs ripple)
    assert pre_arrival(old) > 0.015          # 2.0 %
    il, il_old = (ChannelModel.from_config(c).insertion_loss_db(cfg.f_nyquist) for c in (cfg, old))
    assert il == pytest.approx(il_old, abs=0.1)
    # the inductance the model adds, read back from the ABCD line: at
    # Nyquist, L_int = r_skin / (2 pi sqrt(f_N)) over the geometry's L
    f = np.array([0.0, cfg.f_nyquist])
    from d2d_link.vendor.halo import analytic
    r_, l_, g_, c_ = analytic.skin_effect_rlgc(f, p["rdc_ohm_m"], p["r_skin"], p["l_h_m"], p["c_f_m"],
                                               loss_tangent=p["loss_tangent"], g_per_m=p["g_s_m"])
    l_int = p["r_skin"] / (2 * np.pi * np.sqrt(cfg.f_nyquist))
    assert 0.01 < l_int / p["l_h_m"] < 0.2            # a few percent of the geometry's inductance at 16 GHz
    z_new = analytic.tline_abcd(r_, l_ + np.array([0.0, l_int]), g_, c_, 0.025, f)
    const = dataclasses.replace(cfg, channel=dataclasses.replace(cfg.channel, dielectric="constant"))   # tan d as the vendored RLGC has it
    z_ref = ChannelModel.from_rlgc(const, f).H
    assert abs(analytic.abcd_to_transfer(z_new, 50.0, 50.0)[1] / 0.5) == pytest.approx(abs(z_ref[1]), rel=1e-9)


def test_pulse_window_and_cursor_reach_are_converged():
    """The pulse's time window is 2 (n_freq - 1) / osr UI and the statistical
    engine reads sim.stat_cursor_reach cursors on each side: with the 0.11
    defaults (2048 points = 128 UI, a hard-coded 64) the engine dropped the
    62 cursors past +64 UI while the time engine kept them, and the window's
    end still held 3.5e-3 of the main cursor. Doubling the 9b defaults moves
    the x1 eye by less than the ISI bin."""
    from d2d_link.engine import run_statistical
    base = LinkConfig(channel=ChannelConfig(length_mm=25.0), tx=TxConfig(bw_hz=60e9),
                      sim=SimConfig(stat_phase_points=16))
    r8 = run_statistical(base)
    r16 = run_statistical(dataclasses.replace(base, channel=dataclasses.replace(base.channel, n_freq=16384),
                                              sim=dataclasses.replace(base.sim, stat_cursor_reach=512)))
    assert abs(r16.eye_width_ui - r8.eye_width_ui) < 2e-4
    assert abs(r16.eye_height_v - r8.eye_height_v) < 3e-4
    resp = link_response(base)
    assert resp.pulse.y.size == 2 * (base.channel.n_freq - 1)
    assert resp.cursors(0.0)[0].size > 64 and resp.cursors(0.0, n_max=64)[0].size <= 129
    c, i = resp.cursors(0.0)
    assert np.all(np.abs(c[[0, -1]]) > base.sim.stat_cursor_floor * np.max(np.abs(resp.pulse.y)))
    with pytest.raises(ValueError, match="stat_cursor_reach"):
        SimConfig(stat_cursor_reach=4)


def test_touchstone_band_is_extended_past_the_file(tmp_path, monkeypatch):
    """A file that stops at 50 GHz used to meet a brick wall there (the
    vendored interpolation fills transmission beyond the band with 0 on a grid
    that runs to 512 GHz): the 25 mm line written to such a file read 0.016
    UI less eye width than in closed form. extend_band continues log|H|
    with the last decade's slope and the phase with its group delay."""
    skrf = pytest.importorskip("skrf")
    from d2d_link.channel import model as M
    from d2d_link.config import LaneConfig
    from d2d_link.engine import run_statistical

    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0), sim=SimConfig(stat_phase_points=32))
    ana = ChannelModel.from_config(cfg)
    ref = run_statistical(cfg)

    def write(f_max, name):
        keep = (ana.f > 0) & (ana.f <= f_max)
        f = ana.f[keep]
        s = np.zeros((f.size, 4, 4), dtype=complex)
        for i in range(2):
            s[:, 2 + i, i] = s[:, i, 2 + i] = ana.H[keep]
        skrf.Network(f=f, s=s, z0=50.0, f_unit="Hz").write_touchstone(str(tmp_path / name), form="ri")
        return dataclasses.replace(cfg, channel=ChannelConfig(kind="touchstone", file=str(tmp_path / name) + ".s4p",
                                                              touchstone_mode="single_ended", coupled_length_mm=25.0),
                                   lanes=LaneConfig(count=2))

    cut = write(50e9, "cut50")
    ch = ChannelModel.from_config(cut)
    out = ana.f > 50e9
    assert np.all(np.diff(np.abs(ch.H[out])) <= 1e-12)                        # never rises past the edge
    i100 = int(np.searchsorted(ana.f, 100e9))
    assert abs(20 * np.log10(abs(ch.H[i100]) / abs(ana.H[i100]))) < 2.0        # within 2 dB an octave out
    assert abs(np.angle(ch.H[i100] / ana.H[i100])) < 0.3                        # the group delay carries the phase
    r = run_statistical(cut)
    assert abs(r.eye_width_ui - ref.eye_width_ui) < 0.004
    monkeypatch.setattr(M, "extend_band", lambda H, f, f_edge: H)              # the brick wall, for the record
    wall = run_statistical(cut)
    assert abs(wall.eye_width_ui - ref.eye_width_ui) > 0.008
    monkeypatch.undo()
    full = write(ana.f[-1], "full")
    assert np.allclose(ChannelModel.from_config(full).H[1:], ana.H[1:], rtol=1e-3, atol=1e-6)   # covering the grid: untouched
    assert M.extend_band(ana.H, ana.f, float(ana.f[-1])) is not ana.H


def test_report_labels_touchstone_crosstalk_as_the_files(tmp_path):
    """The report's crosstalk block used to quote the package preset (-30 dB,
    'model') for channel.xtalk touchstone; the file's own coupling at Nyquist
    is the number, source 'file'."""
    skrf = pytest.importorskip("skrf")
    from d2d_link.clock.forwarded import ForwardedClock
    from d2d_link.config import LaneConfig
    from d2d_link.engine import run_link
    from d2d_link.report import report

    cfg = LinkConfig(sim=SimConfig(stat_phase_points=16))
    f = ChannelModel.grid(cfg)[1:]
    thru = np.exp(-2j * np.pi * f * np.sqrt(2.656e-7 * 1.063e-10) * 0.025)
    kx = 0.1 * (1j * f / cfg.f_nyquist) / (1 + 1j * f / cfg.f_nyquist)
    s = np.zeros((f.size, 4, 4), dtype=complex)
    for i in range(2):
        s[:, 2 + i, i] = s[:, i, 2 + i] = thru
    s[:, 2, 1] = s[:, 1, 2] = s[:, 3, 0] = s[:, 0, 3] = kx * thru
    skrf.Network(f=f, s=s, z0=50.0, f_unit="Hz").write_touchstone(str(tmp_path / "pair"), form="ri")
    ts = dataclasses.replace(cfg, channel=ChannelConfig(kind="touchstone", file=str(tmp_path / "pair.s4p"),
                                                        touchstone_mode="single_ended", xtalk="touchstone"),
                             lanes=LaneConfig(count=2))
    res = run_link(ts)
    x = report(ts, res, ForwardedClock(ts))["crosstalk"]
    assert x["mode"] == "touchstone" and x["adjacent_source"] == "file"
    assert x["adjacent_db"] == pytest.approx(20 * np.log10(0.1 / np.sqrt(2.0)), abs=0.3)
    assert res.stat[0].extras["xtalk_source"] == "file"
    fext = report(LinkConfig(channel=ChannelConfig(xtalk="fext"), lanes=LaneConfig(count=2)), res, ForwardedClock(ts))["crosstalk"]
    assert fext["adjacent_source"] == "model"


def test_touchstone_coupling_follows_the_through_path_past_the_band(tmp_path):
    """The coupling terms kept the 0 fill beyond the file's band after 9b (the
    through path alone was extended): the 25 mm line as a 3-lane file with
    FEXT-shaped coupling (-20 / -30 dB at Nyquist, times the line), cut at
    50 GHz, read the middle lane 3.5 mV / 0.010 UI off the full-band file.
    With the coupling following the through path's decay the eye height is
    back within 0.3 mV and the width within 0.006 UI (the through path's own
    extension accounts for that)."""
    skrf = pytest.importorskip("skrf")
    from d2d_link.channel.model import extend_band_like
    from d2d_link.config import LaneConfig
    from d2d_link.engine import run_link

    base = LinkConfig(channel=ChannelConfig(length_mm=25.0), tx=TxConfig(bw_hz=60e9), sim=SimConfig(stat_phase_points=32),
                      lanes=LaneConfig(count=3))
    ana = ChannelModel.from_config(base)
    f_all = ana.f
    kx = 0.1 * np.sqrt(2) * (1j * f_all / base.f_nyquist) / (1 + 1j * f_all / base.f_nyquist)

    def write(f_max, name):
        keep = (f_all > 0) & (f_all <= f_max)
        f = f_all[keep]
        s = np.zeros((f.size, 6, 6), dtype=complex)
        for i in range(3):
            s[:, 3 + i, i] = s[:, i, 3 + i] = ana.H[keep]
            for j in range(3):
                if abs(i - j) == 1:
                    s[:, 3 + i, j] = s[:, j, 3 + i] = (kx * ana.H)[keep]
                elif abs(i - j) == 2:
                    s[:, 3 + i, j] = s[:, j, 3 + i] = (0.3 * kx * ana.H)[keep]
        skrf.Network(f=f, s=s, z0=50.0, f_unit="Hz").write_touchstone(str(tmp_path / name), form="ri")
        return dataclasses.replace(base, channel=ChannelConfig(kind="touchstone", file=str(tmp_path / name) + ".s6p",
                                                               touchstone_mode="single_ended", lane=1, xtalk="touchstone",
                                                               coupled_length_mm=25.0))

    truth = run_link(write(f_all[-1], "full")).stat[1]
    cut = write(50e9, "cut50")
    ch = ChannelModel.from_config(cut)
    out = f_all > 50e9
    assert np.all(np.abs(ch.xtalk_H[1][out]) > 0.0)                                    # no brick wall on the coupling
    i100 = int(np.searchsorted(f_all, 100e9))
    assert abs(20 * np.log10(abs(ch.xtalk_H[1][i100]) / abs((kx * ana.H)[i100]))) < 2.5   # within 2.5 dB an octave out (2.1 on the dispersive line)
    r = run_link(cut).stat[1]
    assert abs(r.eye_height_v - truth.eye_height_v) < 5e-4                            # 0.4 mV on the dispersive line
    # 0.005 UI on 0.12's constant-tan d line; 0.009 on the dispersive one (0.13), where the coupling's
    # extension no longer moves the eye at all -- what is left is the through path's own extrapolation
    assert abs(r.eye_width_ui - truth.eye_width_ui) < 0.012
    # the helper: nothing beyond the edge is left alone; the ratio to the through path is frozen at the edge
    H = np.array([1.0, 0.5, 0.25, 0.125]); X = np.array([0.1, 0.1, 0.0, 0.0]); f = np.array([0.0, 1.0, 2.0, 3.0])
    assert np.allclose(extend_band_like(X, f, 1.0, H), [0.1, 0.1, 0.05, 0.025])
    assert np.array_equal(extend_band_like(X, f, 3.0, H), X)


def test_grid_top_truncation_is_measured_and_warned():
    """The 2 mm advanced line at 4 GT/s on the 32x grid: the grid's top is
    64 GHz, where the 60 GHz driver pole and the line still pass 58 % of the
    signal. The brick wall there rings the impulse (alternating samples) and
    reads the main cursor 7 mV low -- what ROADMAP P2 #1 blamed on the RDL
    line's RC character (phase 12). link_response measures and warns; the
    same config through with_data_rate (osr 256) is clean."""
    import warnings

    from d2d_link.config import PackageConfig, with_data_rate

    base = LinkConfig(package=PackageConfig(kind="advanced"), channel=ChannelConfig(length_mm=2.0), tx=TxConfig(bw_hz=60e9))
    slow = dataclasses.replace(base, data_rate_gtps=4.0)
    with pytest.warns(UserWarning, match="grid's top frequency 64 GHz"):
        r_bad = link_response(slow)
    assert r_bad.grid_top_response > 0.5
    good = with_data_rate(base, 4.0)
    assert good.sim.osr == 256
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        r_good = link_response(good)
    assert r_good.grid_top_response < 0.1
    assert r_good.main_amplitude - r_bad.main_amplitude > 5e-3
    assert np.sum(r_good.cursors(0.0)[0]) == pytest.approx(0.5 * 0.4 * abs(r_good.channel.H[0]), rel=2e-3)   # cursor sum = DC
    assert np.sum(r_bad.cursors(0.0)[0]) < 0.5 * 0.4 * abs(r_bad.channel.H[0]) * 0.97                        # the wall eats it
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert link_response(base).grid_top_response < 0.1                                                 # 32 GT/s: clean



def test_dielectric_is_causal_and_matched_at_its_reference():
    """Phase 15: a constant tan d on a constant C is the dielectric side of the
    non-causality 9b fixed for the skin effect. The Djordjevic-Sarkar
    permittivity has the preset eps' and tan d at loss_tangent_ref_hz, rises
    towards DC and falls above, and the line built from it carries less
    energy before its LC delay than the constant-tan d one."""
    from d2d_link.channel.model import djordjevic_sarkar

    f = np.array([1e8, 1e9, 1e10, 1e11])
    eps = djordjevic_sarkar(f, 0.01, 1e10)
    assert eps[2].real == pytest.approx(1.0, rel=1e-12) and -eps[2].imag / eps[2].real == pytest.approx(0.01, rel=1e-12)
    assert eps[0].real > eps[1].real > eps[2].real > eps[3].real                   # dispersion, as KK requires
    assert np.all(eps.imag < 0.0)                                                   # loss everywhere
    cfg = LinkConfig(channel=ChannelConfig(length_mm=25.0), tx=TxConfig(bw_hz=60e9))
    const = dataclasses.replace(cfg, channel=dataclasses.replace(cfg.channel, dielectric="constant"))
    p = cfg.rlgc()
    n = int(cfg.channel.length_mm * 1e-3 * np.sqrt(p["l_h_m"] * p["c_f_m"]) / cfg.dt) - cfg.sim.osr

    def early(c):
        r = link_response(c)
        return float(np.max(np.abs(r.pulse.y[:n])) / r.main_amplitude)

    assert early(cfg) < 1e-3 < early(const)          # 6e-5 against 3e-3 of the main cursor before the LC delay


def test_single_ended_file_with_the_modules_lanes_is_read_lane_by_lane(tmp_path):
    """A file holding exactly the module's physical lines gives each lane its
    own through and neighbours (0.14.4); until then every lane read
    ``channel.lane``'s (example 08's middle lane was 0.21 mV off). A file
    with another lane count stays a representative group: every lane reads
    ``channel.lane``."""
    skrf = pytest.importorskip("skrf")
    from d2d_link.channel.touchstone_se import file_lanes
    from d2d_link.config import LaneConfig
    from d2d_link.engine import run_link
    from d2d_link.engine.lanes import file_per_lane

    cfg = LinkConfig(sim=SimConfig(stat_phase_points=16))
    f = ChannelModel.grid(cfg)[1:]
    beta = 2 * np.pi * f * np.sqrt(2.656e-7 * 1.063e-10) * 0.025
    n = 3
    s = np.zeros((f.size, 2 * n, 2 * n), dtype=complex)
    for i, loss in enumerate((1.0, 0.9, 0.8)):                       # each lane its own flat loss
        s[:, n + i, i] = s[:, i, n + i] = loss * np.exp(-1j * beta)
    skrf.Network(f=f, s=s, z0=50.0, f_unit="Hz").write_touchstone(str(tmp_path / "three"), form="ri")
    file = str(tmp_path / "three.s6p")
    assert file_lanes(file) == 3 and file_lanes(file, 2) == 2
    own = dataclasses.replace(cfg, channel=ChannelConfig(kind="touchstone", file=file, touchstone_mode="single_ended"),
                              lanes=LaneConfig(count=3))
    assert file_per_lane(own)
    res = run_link(own)
    mains = [r.main_cursor_v for r in res.stat]
    assert mains[1] / mains[0] == pytest.approx(0.9, rel=2e-3) and mains[2] / mains[0] == pytest.approx(0.8, rel=2e-3)
    group = dataclasses.replace(own, lanes=LaneConfig(count=2))      # two lanes of a three-lane file: representative
    assert not file_per_lane(group)
    g = run_link(group)
    assert g.stat[0].main_cursor_v == g.stat[1].main_cursor_v == pytest.approx(mains[0], rel=1e-12)
    assert not file_per_lane(LinkConfig(lanes=LaneConfig(count=3)))


def test_per_lane_file_with_behavioural_fext_keeps_the_cos_factor(tmp_path):
    """A Touchstone through with behavioural FEXT on top: the per-lane file
    path and the representative path give the through the same cos factor
    (0.15.5; until then the per-lane path dropped it -- sixth health check)."""
    skrf = pytest.importorskip("skrf")
    from d2d_link.config import LaneConfig
    from d2d_link.engine import run_link

    cfg = LinkConfig(sim=SimConfig(stat_phase_points=16))
    ana = ChannelModel.from_config(cfg)
    f = ana.f[1:]
    n = 3
    s = np.zeros((f.size, 2 * n, 2 * n), dtype=complex)
    for i in range(n):
        s[:, n + i, i] = s[:, i, n + i] = ana.H[1:]
    skrf.Network(f=f, s=s, z0=50.0, f_unit="Hz").write_touchstone(str(tmp_path / "flat3"), form="ri")
    ch = ChannelConfig(kind="touchstone", file=str(tmp_path / "flat3.s6p"), touchstone_mode="single_ended", lane=1,
                       xtalk="fext", xtalk_adjacent_db=-20.0, coupled_length_mm=25.0)
    per_lane = run_link(dataclasses.replace(cfg, channel=ch, lanes=LaneConfig(count=3)))
    # the representative path (a 4-lane module on a 3-lane file reads lane 1 for every lane, and the file's lanes
    # are identical): lane 0 has one line on each distance in both modules
    group = run_link(dataclasses.replace(cfg, channel=ch, lanes=LaneConfig(count=4)))
    assert per_lane.stat[0].main_cursor_v == pytest.approx(group.stat[0].main_cursor_v, rel=1e-9)
    plain = run_link(dataclasses.replace(cfg, channel=dataclasses.replace(ch, xtalk="none"), lanes=LaneConfig(count=3)))
    assert per_lane.stat[0].main_cursor_v < plain.stat[0].main_cursor_v          # the cos factor is there
