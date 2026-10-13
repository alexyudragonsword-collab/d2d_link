"""Single-ended multi-port Touchstone files: a module's lanes with their coupling.

UCIe lanes are single-ended, so a package extraction of a lane group comes as
a 2N-port file: here ports 1..N are the near (transmit) ends of lanes 0..N-1
and ports N+1..2N their far (receive) ends -- the "all inputs, then all
outputs" convention; a file ordered otherwise is renumbered before use. The
vendored Halo reader (``vendor/halo/touchstone.py``) handles differential
pairs; this helper sits beside it, untouched, and reuses its interpolation
and termination for every 2-port sub-network it cuts out:

* the lane's through path, ports (lane, N + lane);
* far-end crosstalk from a neighbour ``j`` places away, ports (lane +- j,
  N + lane) -- the file's own coupling, no behavioural shape.

With every other port terminated in the file's reference impedance, the
2-port sub-network's S-parameters are exactly the transfer the file
describes; renormalising its two ports to the configured terminations is
the one approximation (the other lanes are assumed matched).
"""

from __future__ import annotations

import numpy as np


def read_single_ended(path: str, f: np.ndarray, zs: float, zl: float, lane: int,
                      n_lanes: int | None = None, neighbours: tuple[int, ...] = (1, 2)) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    """``(H, {d: Hx})``: the victim lane's terminated voltage transfer on
    grid ``f`` and, for each neighbour distance ``d`` present in the file,
    the aggressor-to-victim far-end transfer of the *stronger* of the two
    neighbours at that distance (its RMS over the grid). Both are normalised
    like ``ChannelModel.from_touchstone``: a lossless matched line reads 1."""
    import skrf as rf

    from ..vendor.halo.touchstone import interp_s2p, terminate_renormalize

    ntwk = rf.Network(str(path))
    n_ports = ntwk.s.shape[1]
    n = n_lanes if n_lanes is not None else n_ports // 2
    if n_ports != 2 * n:
        raise ValueError(f"{path}: {n_ports} ports do not hold {n} single-ended lanes (need 2N)")
    if not 0 <= lane < n:
        raise ValueError(f"{path}: lane {lane} outside 0..{n - 1}")
    norm = zl / (zs + zl)

    def transfer(p_in: int, p_out: int) -> np.ndarray:
        from .model import fill_dc

        sub = ntwk.subnetwork([p_in, p_out])
        return fill_dc(terminate_renormalize(interp_s2p(sub, f), zs, zl) / norm, f)

    H = transfer(lane, n + lane)
    xt: dict[int, np.ndarray] = {}
    for d in neighbours:
        cands = [transfer(j, n + lane) for j in (lane - d, lane + d) if 0 <= j < n]
        if cands:
            xt[d] = max(cands, key=lambda h: float(np.sqrt(np.mean(np.abs(h) ** 2))))
    return H, xt


__all__ = ["read_single_ended"]
