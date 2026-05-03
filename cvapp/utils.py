from __future__ import annotations

import datetime as dt
import re


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "default"


def pretty_name(value: str) -> str:
    words = value.replace("-", " ").split()
    return " ".join(word[:1].upper() + word[1:].lower() for word in words)


def normalize_tag(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[`*_#>\[\](){}]", " ", value)
    value = re.sub(r"[^a-z0-9+.#/& -]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .-_/&:")
    return value


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_iso(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def quote_env(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def unquote_env(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        inner = value[1:-1]
        return bytes(inner, "utf-8").decode("unicode_escape")
    return value
