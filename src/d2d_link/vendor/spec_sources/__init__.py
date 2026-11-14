"""spec_sources, vendored: the shared table of numbers about the outside world.

Pinned at spec_sources@bbc0ccb49de4e0071e0bc21ea6bbe73fd92e1428 (main, the
merge of PR #19, milestone 2: 15 of the 16 UCIe numbers checked against
the consortium's public material, source spec; issue #2; first pinned at
d7b4d1e, PR #1). Copied verbatim under the two-line header:
``reader.py`` (the reader and its guards), ``data/ucie.yaml`` (the UCIe
numbers, keys ``ucie.*``: the 16 this library reads by its old keys, plus
``ucie.raw_ber_by_rate`` and ``ucie.advanced.spare_lanes_per_32`` read by
their full names) and ``legacy_keys/d2d_link.yaml``
(this library's old bare keys -> those keys). ``d2d_link.spec`` is the shim
that reads them under the old keys. Only the UCIe table is copied: the
reader loads whatever ``data/*.yaml`` sits next to it. A change to a number
is made upstream and re-pinned here (``tools/vendor_check.py`` checks the
copies against the pin); this ``__init__.py`` is d2d_link's own.
"""

from . import reader

__all__ = ["reader"]
