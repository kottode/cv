from __future__ import annotations

import re
from pathlib import Path

from ..utils import unquote_env


def load_env_style_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = unquote_env(value.strip())
    return values


def parse_env_bool(value: str, default: bool = False) -> bool:
    token = (value or "").strip().lower()
    if token in {"1", "true", "yes", "on", "enabled", "enable"}:
        return True
    if token in {"0", "false", "no", "off", "disabled", "disable"}:
        return False
    return default


def parse_env_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def parse_env_list(value: str) -> list[str]:
    raw = str(value or "")
    parts = [chunk.strip() for chunk in re.split(r"[\n,;|]", raw) if chunk.strip()]
    seen: set[str] = set()
    values: list[str] = []
    for item in parts:
        if item in seen:
            continue
        seen.add(item)
        values.append(item)
    return values
