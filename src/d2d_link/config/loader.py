"""YAML <-> LinkConfig with strict keys (Halo_Serdes ``config/loader.py`` method).

Unknown keys are an error; missing keys take the dataclass defaults; dotted
overrides are grouped per dataclass so validation that spans two fields sees
them together. PyYAML is imported inside the functions so the schema stays
importable without it.
"""

from __future__ import annotations

import dataclasses
import typing
import warnings
from pathlib import Path
from typing import Any, Union

from .schema import SCHEMA_VERSION, LinkConfig


def _unwrap_optional(tp: Any) -> Any:
    if typing.get_origin(tp) is Union:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp


def _coerce(tp: Any, value: Any, path: str) -> Any:
    """YAML 1.1 reads ``32.0e9`` as a string and ``1e-27`` too; coerce to the
    annotated scalar type so configs stay human-friendly."""
    if value is None:
        return None
    try:
        if tp is float and not isinstance(value, float):
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        if tp is int and not isinstance(value, int):
            as_float = float(value)
            if not as_float.is_integer():
                raise ValueError(f"{path}: expected integer, got {value!r}")
            return int(as_float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path}: cannot convert {value!r} to {getattr(tp, '__name__', tp)}") from exc
    return value


#: keys an older config file may still use -> their current name (a
#: DeprecationWarning is raised, the value is kept)
RENAMED_KEYS: dict[tuple[str, str], str] = {("ClockingConfig", "local_pll_bw_hz"): "local_pll_fn_hz"}


def _build(cls: type, data: dict[str, Any], path: str) -> Any:
    if not isinstance(data, dict):
        raise TypeError(f"{path}: expected mapping, got {type(data).__name__}")
    hints = typing.get_type_hints(cls)
    fields = {f.name: f for f in dataclasses.fields(cls)}
    kwargs: dict[str, Any] = {}
    data = dict(data)
    for (owner, old), new in RENAMED_KEYS.items():
        if cls.__name__ == owner and old in data:
            if new in data:
                raise KeyError(f"{path}: both {old!r} and its new name {new!r} are set")
            warnings.warn(f"{path}.{old} was renamed {new} (it is the loop's natural frequency, not its "
                          f"-3 dB bandwidth); update the config", DeprecationWarning, stacklevel=4)
            data[new] = data.pop(old)
    for key, value in data.items():
        if key not in fields:
            raise KeyError(f"{path}: unknown config key {key!r} (valid: {sorted(fields)})")
        tp = _unwrap_optional(hints[key])
        if dataclasses.is_dataclass(tp) and isinstance(value, dict):
            kwargs[key] = _build(tp, value, f"{path}.{key}")
        elif typing.get_origin(tp) is tuple and isinstance(value, (list, tuple)):
            inner = typing.get_args(tp)
            elem = inner[0] if inner else Any
            kwargs[key] = tuple(_coerce(elem, v, f"{path}.{key}[{i}]") for i, v in enumerate(value))
        else:
            kwargs[key] = _coerce(tp, value, f"{path}.{key}")
    return cls(**kwargs)


def config_from_dict(data: dict[str, Any]) -> LinkConfig:
    data = dict(data)
    version = data.pop("schema_version", SCHEMA_VERSION)
    if version > SCHEMA_VERSION:
        raise ValueError(f"config schema_version {version} is newer than supported {SCHEMA_VERSION}")
    return _build(LinkConfig, data, "link")


def load_config(path: str | Path, overrides: dict[str, Any] | None = None) -> LinkConfig:
    """Load a LinkConfig from YAML; ``overrides`` is a flat dotted-path dict."""
    import yaml

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    cfg = config_from_dict(data)
    if overrides:
        cfg = apply_overrides(cfg, overrides)
    return cfg


def apply_overrides(cfg: LinkConfig, overrides: dict[str, Any]) -> LinkConfig:
    """A copy of ``cfg`` with dotted-path overrides, one ``replace`` per dataclass."""
    tree: dict[str, Any] = {}
    for dotted, value in overrides.items():
        parts = dotted.split(".")
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise KeyError(f"override {dotted!r} descends into a field another override sets whole")
        node[parts[-1]] = value
    return _replace_tree(cfg, tree)


def _replace_tree(obj: Any, tree: dict[str, Any]) -> Any:
    names = {f.name for f in dataclasses.fields(obj)}
    hints = typing.get_type_hints(type(obj))
    kwargs: dict[str, Any] = {}
    for key, value in tree.items():
        if key not in names:
            raise KeyError(f"unknown config field {key!r} on {type(obj).__name__}")
        child = getattr(obj, key)
        if isinstance(value, dict) and dataclasses.is_dataclass(child):
            kwargs[key] = _replace_tree(child, value)
        else:
            tp = _unwrap_optional(hints[key])
            if typing.get_origin(tp) is tuple and isinstance(value, list):
                value = tuple(value)
            kwargs[key] = value
    return dataclasses.replace(obj, **kwargs)


def config_to_dict(cfg: LinkConfig) -> dict[str, Any]:
    data = _tuples_to_lists(dataclasses.asdict(cfg))
    data["schema_version"] = SCHEMA_VERSION
    return data


def dump_config(cfg: LinkConfig, path: str | Path) -> None:
    """Write ``cfg`` to YAML; round-trips through ``load_config``."""
    import yaml

    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(config_to_dict(cfg), fh, sort_keys=False, allow_unicode=True)


def _tuples_to_lists(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _tuples_to_lists(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return [_tuples_to_lists(v) for v in obj]
    return obj


__all__ = ["load_config", "dump_config", "apply_overrides", "config_from_dict", "config_to_dict"]
