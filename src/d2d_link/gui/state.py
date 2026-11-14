"""Page state and the provenance of every field (invariant #5 on screen).

One browser, one ``PageState``: the config file, the overrides the page has
accumulated on top of it, the job that produced the result on screen. The
state never computes anything; ``source_of`` only classifies where a value
came from so the drawer can say ``yaml`` / ``default`` / ``model`` / ``spec`` / ``survey``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from ..channel.coupled import trace_pitch_um
from ..config import LinkConfig, apply_overrides, load_config
from ..config.form import FIELDS, config_to_values
from ..config.schema import RLGC_PRESET_KEYS, STACKUP_KEYS
from ..spec import survey_tiered

MODEL_PRESET_PATHS = {f"channel.{k}" for k in (*RLGC_PRESET_KEYS, *STACKUP_KEYS)} | {
    "channel.xtalk_adjacent_db", "channel.xtalk_second_db", "channel.trace_pitch_um"}
SURVEY_PATHS = {"target.ber": "raw_ber_target", "target.eye_height_mv": "rx_eye_height_mv",   # field -> table key (as engine.statistical.target_keys)
                "target.eye_width_ui": "rx_eye_width_ui"}


def _get(obj: Any, path: str) -> Any:
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def source_of(cfg: LinkConfig, path: str, file_cfg: LinkConfig | None = None) -> str:
    """Where the value on screen comes from: ``override`` (edited on the
    page), ``yaml`` (set in the file), ``default`` (the schema's), ``model``
    (empty, resolved from a model preset) or the table entry's own tag,
    ``spec`` or ``survey`` (empty, resolved from the vendored UCIe table;
    since 0.16.1 most entries are ``spec``)."""
    v = _get(cfg, path)
    if v is None:
        if path in SURVEY_PATHS:
            return survey_tiered(SURVEY_PATHS[path], cfg.package.kind, cfg.data_rate_gtps).source
        if path == "channel.trace_pitch_um":
            return trace_pitch_um(cfg)[1]
        if path in MODEL_PRESET_PATHS:
            return "model"
        return "default"
    if file_cfg is not None and _get(file_cfg, path) != v:
        return "override"
    try:
        default = _get(LinkConfig(), path)
    except Exception:          # noqa: BLE001 -- a default config may not build for every tree
        default = None
    return "default" if default == v else "yaml"


@dataclasses.dataclass
class PageState:
    config_path: Path | None = None
    file_cfg: LinkConfig | None = None
    overrides: dict[str, Any] = dataclasses.field(default_factory=dict)
    job_id: str | None = None          # the run whose result is on screen
    selected_lane: int | None = None
    compare_path: Path | None = None   # another scenario shown beside this one

    @property
    def cfg(self) -> LinkConfig:
        base = self.file_cfg if self.file_cfg is not None else LinkConfig()
        return apply_overrides(base, self.overrides) if self.overrides else base

    def open(self, path: Path) -> None:
        file_cfg = load_config(path)            # a file that does not load leaves the page as it was
        self.config_path = Path(path)
        self.file_cfg = file_cfg
        self.overrides = {}
        self.job_id = None
        self.selected_lane = None

    def set(self, path: str, value: Any) -> None:
        """One override; a value equal to the file's drops the override."""
        if self.file_cfg is not None and _get(self.file_cfg, path) == value:
            self.overrides.pop(path, None)
        else:
            self.overrides[path] = value

    def values(self) -> dict[str, Any]:
        return config_to_values(self.cfg)

    def rows(self) -> list[dict]:
        """Every form field with its display value, kind and source."""
        vals = self.values()
        out = []
        for path, fld in FIELDS.items():
            out.append({"path": path, "label": fld["label"], "kind": fld["kind"], "value": vals[path],
                        "options": fld.get("options"), "source": source_of(self.cfg, path, self.file_cfg)})
        return out

    def diff(self) -> list[tuple[str, Any, Any]]:
        """(path, file value, page value) for every override."""
        base = self.file_cfg if self.file_cfg is not None else LinkConfig()
        return [(p, _get(base, p), v) for p, v in self.overrides.items()]


__all__ = ["PageState", "source_of"]
