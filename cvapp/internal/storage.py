from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from ..config import LEGACY_TRACK_FILE, CVState
from ..errors import die
from ..internal.project import current_posts_path, current_track_path
from ..utils import now_iso, parse_iso


TRACK_FIELDS = ["item", "status", "updated_at", "applied_at"]


def _read_track_rows_from_delimited(path: Path, delimiter: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.reader(fp, delimiter=delimiter)
        for idx, parts in enumerate(reader):
            if idx == 0 and [part.strip().lower() for part in parts[:4]] == TRACK_FIELDS:
                continue
            if not parts or not any(cell.strip() for cell in parts):
                continue
            while len(parts) < 4:
                parts.append("")
            item, status, updated_at, applied_at = parts[:4]
            rows.append(
                {
                    "item": item,
                    "status": status,
                    "updated_at": updated_at,
                    "applied_at": applied_at,
                }
            )
    return rows


def ensure_track_file(root: Path, state: CVState) -> Path:
    path = root / current_track_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.is_file():
        legacy_candidates: list[Path] = []
        tsv_path = path.with_suffix(".tsv")
        if tsv_path.is_file():
            legacy_candidates.append(tsv_path)

        legacy_path = root / LEGACY_TRACK_FILE
        if state.current_job == "default" and legacy_path.is_file():
            legacy_candidates.append(legacy_path)

        for candidate in legacy_candidates:
            if not candidate.is_file():
                continue
            delimiter = "\t" if candidate.suffix.lower() == ".tsv" else ","
            rows = _read_track_rows_from_delimited(candidate, delimiter)
            write_track_rows(path, rows)
            break

    if not path.is_file():
        write_track_rows(path, [])
    return path


def ensure_posts_file(root: Path, state: CVState) -> Path:
    path = root / current_posts_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        payload = {
            "version": 1,
            "updated_at": now_iso(),
            "posts": [],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def load_posts(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        posts = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("posts"), list):
        posts = parsed.get("posts")
    else:
        posts = []

    valid_posts: list[dict[str, Any]] = []
    for item in posts:
        if isinstance(item, dict):
            valid_posts.append(item)
    return valid_posts


def save_posts(path: Path, posts: list[dict[str, Any]]) -> None:
    ordered = sorted(posts, key=lambda row: str(row.get("updated_at", "")), reverse=True)
    payload = {
        "version": 1,
        "updated_at": now_iso(),
        "posts": ordered,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def upsert_post_record(posts: list[dict[str, Any]], record: dict[str, Any]) -> bool:
    from .web import normalize_url

    target_url = normalize_url(str(record.get("url", "")))
    for row in posts:
        row_url = normalize_url(str(row.get("url", "")))
        if row_url != target_url:
            continue

        first_seen = row.get("first_seen_at") or row.get("discovered_at") or now_iso()
        existing_apply_status = str(row.get("apply_status", "")).strip()
        existing_applied_at = str(row.get("applied_at", "")).strip()
        existing_track_item = str(row.get("track_item", "")).strip()

        row.update(record)
        row["first_seen_at"] = first_seen
        if existing_apply_status == "applied" and row.get("apply_status") != "applied":
            row["apply_status"] = existing_apply_status
        if existing_applied_at and not row.get("applied_at"):
            row["applied_at"] = existing_applied_at
        if existing_track_item and not row.get("track_item"):
            row["track_item"] = existing_track_item
        return False

    posts.append(record)
    return True


def read_track_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    return _read_track_rows_from_delimited(path, ",")


def write_track_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(TRACK_FIELDS)
        for row in rows:
            writer.writerow(
                [
                    row.get("item", ""),
                    row.get("status", ""),
                    row.get("updated_at", ""),
                    row.get("applied_at", ""),
                ]
            )


def maybe_mark_ghosted(path: Path) -> list[dict[str, str]]:
    rows = read_track_rows(path)
    now = dt.datetime.now(dt.timezone.utc)
    changed = False

    for row in rows:
        status = row.get("status", "")
        if status != "applied" and not status.startswith("interview"):
            continue
        applied_dt = parse_iso(row.get("applied_at", ""))
        if applied_dt is None:
            continue
        days = (now - applied_dt).days
        if days >= 30:
            row["status"] = "ghosted"
            row["updated_at"] = now_iso()
            changed = True

    if changed:
        write_track_rows(path, rows)
    return rows


def upsert_track_item(path: Path, item: str, status: str) -> dict[str, str]:
    rows = maybe_mark_ghosted(path)
    now = now_iso()

    for row in rows:
        if row.get("item") != item:
            continue
        if not row.get("applied_at") or status == "applied":
            row["applied_at"] = now
        row["status"] = status
        row["updated_at"] = now
        write_track_rows(path, rows)
        return row

    row = {
        "item": item,
        "status": status,
        "updated_at": now,
        "applied_at": now,
    }
    rows.append(row)
    write_track_rows(path, rows)
    return row


def status_token_to_full(token: str) -> str:
    token = token.lower()
    if token in {"", "applied", "a"}:
        return "applied"
    if token in {"interview", "i", "int"}:
        return "interview1"
    match = re.fullmatch(r"(?:i|int)(\d+)", token)
    if match:
        return f"interview{match.group(1)}"
    if token in {"rejected", "r"}:
        return "rejected"
    if token in {"offer", "o"}:
        return "offer"
    if token in {"ghosted", "g"}:
        return "ghosted"
    if token == "status":
        return "status"
    die(f"Unknown status token: {token}")
    return ""


def is_status_token(token: str) -> bool:
    token = token.lower()
    if token in {"applied", "a", "interview", "i", "int", "rejected", "r", "offer", "o", "ghosted", "g", "status"}:
        return True
    return re.fullmatch(r"(?:i|int)\d+", token) is not None
