from __future__ import annotations

from pathlib import Path

from ...config import CVState
from ...errors import die
from ...internal.project import load_state, require_project
from ...internal.storage import (
    ensure_track_file as storage_ensure_track_file,
    is_status_token as storage_is_status_token,
    maybe_mark_ghosted as storage_maybe_mark_ghosted,
    read_track_rows,
    status_token_to_full,
    upsert_track_item,
    write_track_rows,
)
from ...strings import USAGE_TRACK


def ensure_track_file(root: Path, state: CVState) -> Path:
    return storage_ensure_track_file(root, state)


def read_rows(path: Path) -> list[dict[str, str]]:
    return read_track_rows(path)


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    write_track_rows(path, rows)


def maybe_mark_ghosted(path: Path) -> list[dict[str, str]]:
    return storage_maybe_mark_ghosted(path)


def upsert_item(path: Path, item: str, status: str) -> dict[str, str]:
    return upsert_track_item(path, item, status)


def status_from_token(token: str) -> str:
    return status_token_to_full(token)


def is_status_token(token: str) -> bool:
    return storage_is_status_token(token)


def cmd_track(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    path = ensure_track_file(root, state)

    if not args:
        rows = maybe_mark_ghosted(path)
        print(f"{'ITEM':30} {'STATUS':12} {'UPDATED':25} {'APPLIED':25}")
        print(f"{'-' * 30} {'-' * 12} {'-' * 25} {'-' * 25}")
        for row in rows:
            print(f"{row['item'][:30]:30} {row['status'][:12]:12} {row['updated_at'][:25]:25} {row['applied_at'][:25]:25}")
        return 0

    status = ""
    if len(args) >= 2 and is_status_token(args[-1]):
        status = status_from_token(args[-1])

    rows = maybe_mark_ghosted(path)

    if status == "status":
        item = " ".join(args[:-1]).strip()
        if not item:
            die("Usage: cv track <item> status")
        for row in rows:
            if row["item"] == item:
                print(f"Item: {row['item']}")
                print(f"Status: {row['status']}")
                print(f"Updated: {row['updated_at']}")
                print(f"Applied: {row['applied_at']}")
                return 0
        die(f"Track item not found: {item}")

    if status:
        item = " ".join(args[:-1]).strip()
    else:
        item = " ".join(args).strip()
        status = "applied"

    if not item:
        die(USAGE_TRACK)

    upsert_item(path, item, status)
    print(f"Tracked \"{item}\" as {status}")
    return 0
