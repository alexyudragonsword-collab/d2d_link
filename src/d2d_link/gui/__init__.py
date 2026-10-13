"""The browser GUI (phase 8): a report that is the interface.

The page is the timing budget of ``d2d_link.report`` rendered section by
section in the order of what decides the verdict, with the headline's values
as controls. It holds no simulation logic (invariant #1): it edits overrides
of a frozen ``LinkConfig``, hands the config to ``run_link`` on a worker
process, and renders ``LinkResult`` and the report dict it gets back.
``tests/test_gui.py`` keeps its imports to that surface.

    d2d-link-gui configs/standard_32g_x16_module.yaml      # pip install d2d-link[gui]
"""

__all__ = ["create_app", "main"]


def create_app(*args, **kwargs):
    from .app import create_app as _create

    return _create(*args, **kwargs)


def main(argv=None) -> int:
    from .app import main as _main

    return _main(argv)
