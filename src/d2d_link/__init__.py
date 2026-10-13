"""d2d_link: behavioural simulation of die-to-die / UCIe short-reach parallel links.

The configuration (``d2d_link.config.LinkConfig``) is the single source of
truth; the forwarded clock (``d2d_link.clock.forwarded``) is the core
mechanism; the statistical engine (``d2d_link.engine.statistical``) is the
primary engine and the time-domain engine its cross-check at measurable BER.
"""

__version__ = "0.8.0"
