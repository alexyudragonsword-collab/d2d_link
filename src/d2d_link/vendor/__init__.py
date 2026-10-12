"""Vendored (adapted-copy) modules from sibling repositories.

d2d_link is self-contained: it imports neither Halo_Serdes nor pll_simulator.
What it needs from them is copied here, pinned to the upstream commit named
in each file's header, and checked against that commit by
``tools/vendor_check.py`` (the ``vendor-drift`` CI job fails on any
undeclared edit). The policy is polar_tx's:

* ``# Vendored from <repo>@<full sha>: <upstream path>`` on line one, the
  policy pointer on line two;
* a copy is **verbatim** (byte-identical after the header) or **adapted**
  (only ``import`` lines and lines marked ``# d2d_link`` differ); anything
  else must be declared in ``tools/vendor_manifest.json`` with a body hash
  and a reason;
* fixes go upstream and are pulled by re-copying, never made in place.

What is here and why:

- ``halo/touchstone.py``, ``halo/analytic.py``, ``halo/response.py``,
  ``halo/waveform.py`` (Halo_Serdes ``channel/`` and ``core/waveform.py``):
  the S-parameter reader (single-ended 4-port -> mixed-mode -> terminated
  voltage transfer, with the serdespy cross-check), the RLGC lossy
  transmission-line model and the H(f) -> impulse conversions. The channel
  reading is the only part of Halo this library shares; its equalisers,
  CDRs and FEC are the long-reach problem and stay there.
- ``pllsim/colored.py`` (``synth_from_psd``) and ``pllsim/jitter.py``
  (``integrate_pn``, ``sphi_from_ldbc``): the two primitives that turn a
  clock phase-noise profile file (pll_simulator's ``export/clock_profile.py``)
  into per-edge timing and into an integrated jitter. The forwarded clock
  and the data both come from that profile (invariant #2).

Everything else in d2d_link imports these only through ``d2d_link.vendor``
so the seam stays in one place.
"""
