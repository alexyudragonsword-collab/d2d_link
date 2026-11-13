"""spec_sources, vendored: the shared table of numbers about the outside world.

Pinned at spec_sources@d7b4d1eb510617d69784622c593c8ed31ab32b8b (main, the
merge of its milestone 1, PR #1). Copied verbatim under the two-line header:
``reader.py`` (the reader and its guards), ``data/ucie.yaml`` (the 16 UCIe
numbers this library uses, keys ``ucie.*``) and ``legacy_keys/d2d_link.yaml``
(this library's old bare keys -> those keys). ``d2d_link.spec`` is the shim
that reads them under the old keys. Only the UCIe table is copied: the
reader loads whatever ``data/*.yaml`` sits next to it. A change to a number
is made upstream and re-pinned here (``tools/vendor_check.py`` checks the
copies against the pin); this ``__init__.py`` is d2d_link's own.
"""

from . import reader

__all__ = ["reader"]
