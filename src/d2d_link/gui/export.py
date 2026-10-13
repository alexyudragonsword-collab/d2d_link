"""What leaves the page: the same Markdown the CLI prints, the report JSON,
the overrides as YAML. Nothing here adds a number the report does not hold."""

from __future__ import annotations

import json

import yaml

from ..report import sensitivity_markdown, to_markdown


def markdown(result: dict) -> str:
    md = to_markdown(result["report"])
    sens = result.get("sensitivity")
    if sens:
        md += "\n" + sensitivity_markdown(sens)
    return md


def report_json(result: dict) -> str:
    rep = dict(result["report"])
    if result.get("sensitivity"):
        rep["sensitivity"] = result["sensitivity"]
    return json.dumps(rep, indent=1)


def overrides_yaml(config_path, overrides: dict) -> str:
    """The page's edits as a YAML the CLI could replay (``load_config(path,
    overrides)``), with the file they apply to in a comment."""
    head = f"# overrides on {config_path}\n" if config_path else "# overrides\n"
    body = yaml.safe_dump({k: (list(v) if isinstance(v, tuple) else v) for k, v in overrides.items()},
                          sort_keys=True, allow_unicode=True) if overrides else "{}\n"
    return head + body


__all__ = ["markdown", "report_json", "overrides_yaml"]
