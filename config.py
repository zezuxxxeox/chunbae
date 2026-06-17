from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SiteTarget:
    name: str
    board_urls: list[str]
    page_range: tuple[int, int] = (1, 1)
    max_items: int = 50
    sleep_interval: float = 1.0
    render_js: bool = False
    content_type: str = "post"
    terms_ok: bool = False
    include_url_patterns: list[str] = field(default_factory=list)
    exclude_url_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CollectorConfig:
    user_agent: str
    raw_dir: Path
    log_dir: Path
    allow_if_robots_unavailable: bool
    targets: list[SiteTarget]


def load_config(path: str | Path = "sites.yaml") -> CollectorConfig:
    config_path = Path(path)
    payload = _load_mapping(config_path)
    targets = [_target_from_mapping(item) for item in payload.get("targets", [])]
    return CollectorConfig(
        user_agent=str(payload.get("user_agent", "AjoossiStyleResearchBot/0.1")),
        raw_dir=Path(payload.get("raw_dir", "data/raw")),
        log_dir=Path(payload.get("log_dir", "logs")),
        allow_if_robots_unavailable=bool(payload.get("allow_if_robots_unavailable", False)),
        targets=targets,
    )


def expand_board_urls(target: SiteTarget) -> list[str]:
    start, end = target.page_range
    urls: list[str] = []
    for template in target.board_urls:
        if "{page}" in template:
            urls.extend(template.format(page=page) for page in range(start, end + 1))
        else:
            urls.append(template)
    return urls


def _target_from_mapping(item: dict[str, Any]) -> SiteTarget:
    page_range = item.get("page_range", [1, 1])
    if isinstance(page_range, int):
        page_range = [page_range, page_range]
    return SiteTarget(
        name=str(item["name"]),
        board_urls=[str(url) for url in item.get("board_urls", [])],
        page_range=(int(page_range[0]), int(page_range[1])),
        max_items=int(item.get("max_items", 50)),
        sleep_interval=float(item.get("sleep_interval", 1.0)),
        render_js=bool(item.get("render_js", False)),
        content_type=str(item.get("content_type", "post")),
        terms_ok=bool(item.get("terms_ok", False)),
        include_url_patterns=[str(v) for v in item.get("include_url_patterns", [])],
        exclude_url_patterns=[str(v) for v in item.get("exclude_url_patterns", [])],
    )


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)

    try:
        import yaml  # type: ignore
    except ImportError:
        return _parse_small_yaml(text)
    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a mapping")
    return loaded


def _parse_small_yaml(text: str) -> dict[str, Any]:
    """Small YAML subset parser for this project's default sites.yaml shape."""

    result: dict[str, Any] = {}
    current_target: dict[str, Any] | None = None
    current_list_key: str | None = None
    in_targets = False

    for raw_line in text.splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue

        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        line = line_without_comment.strip()

        if indent == 0:
            current_target = None
            current_list_key = None
            if line == "targets:":
                result["targets"] = []
                in_targets = True
                continue
            in_targets = False
            key, value = _split_yaml_pair(line)
            result[key] = _parse_scalar(value)
            continue

        if not in_targets:
            continue

        if indent == 2 and line.startswith("- "):
            current_target = {}
            result.setdefault("targets", []).append(current_target)
            current_list_key = None
            rest = line[2:].strip()
            if rest:
                key, value = _split_yaml_pair(rest)
                current_target[key] = _parse_scalar(value)
            continue

        if current_target is None:
            continue

        if indent == 4:
            if line.startswith("- ") and current_list_key:
                current_target[current_list_key].append(_parse_scalar(line[2:].strip()))
                continue
            key, value = _split_yaml_pair(line)
            if value == "":
                current_target[key] = []
                current_list_key = key
            else:
                current_target[key] = _parse_scalar(value)
                current_list_key = None
            continue

        if indent >= 6 and line.startswith("- ") and current_list_key:
            current_target[current_list_key].append(_parse_scalar(line[2:].strip()))

    return result


def _split_yaml_pair(line: str) -> tuple[str, str]:
    if ":" not in line:
        raise ValueError(f"Invalid config line: {line}")
    key, value = line.split(":", 1)
    return key.strip(), value.strip()


def _parse_scalar(value: str) -> Any:
    if value == "":
        return ""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    if value.startswith("[") and value.endswith("]"):
        return ast.literal_eval(value)
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
