from __future__ import annotations

from pathlib import Path
from typing import Any

from ...config import CVState
from ...errors import die
from ...internal.auto_config import load_auto_config
from ...internal.posts_pipeline import fetch_posts_from_jobspy, fit_cached_posts
from ...internal.project import load_state, require_project
from ...internal.storage import (
    ensure_posts_file as storage_ensure_posts_file,
    load_posts as storage_load_posts,
    save_posts as storage_save_posts,
    upsert_post_record as storage_upsert_post_record,
)
from ...strings import USAGE_POSTS


def ensure_posts_file(root: Path, state: CVState) -> Path:
    return storage_ensure_posts_file(root, state)


def load_posts(path: Path) -> list[dict[str, Any]]:
    return storage_load_posts(path)


def save_posts(path: Path, posts: list[dict[str, Any]]) -> None:
    storage_save_posts(path, posts)


def upsert_post_record(posts: list[dict[str, Any]], record: dict[str, Any]) -> bool:
    return storage_upsert_post_record(posts, record)


def _sort_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(posts, key=lambda row: str(row.get("updated_at", "")), reverse=True)


def _print_rows(root: Path, path: Path, rows: list[dict[str, Any]], posts_total: int) -> None:
    print(f"Posts file: {path.relative_to(root)}")
    print(f"Showing {len(rows)} of {posts_total} posts")
    print(f"{'#':>3} {'GRADE':5} {'FIT':5} {'STATUS':10} {'APPLY':14} {'COMPANY':16} {'TITLE':32}")
    print(f"{'-' * 3} {'-' * 5} {'-' * 5} {'-' * 10} {'-' * 14} {'-' * 16} {'-' * 32}")

    for idx, row in enumerate(rows, start=1):
        grade = str(row.get("grade", "D"))[:5]
        score = int(row.get("fit_score", 0)) if str(row.get("fit_score", "")).isdigit() else row.get("fit_score", 0)
        status = str(row.get("status", ""))[:10]
        apply_status = str(row.get("apply_status", ""))[:14]
        company = str(row.get("company", ""))[:16]
        title = str(row.get("title", ""))[:32]
        print(f"{idx:>3} {grade:5} {str(score)[:5]:5} {status:10} {apply_status:14} {company:16} {title:32}")

    print("Use: cv posts show <index> for full details")


def cmd_posts(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    path = ensure_posts_file(root, state)
    posts = load_posts(path)

    action = args[0].lower() if args else "list"

    if action == "fetch":
        config = load_auto_config(root)
        summary = fetch_posts_from_jobspy(root, state, config, posts)
        save_posts(path, posts)
        print("Posts fetch complete.")
        print("Source: JobSpy")
        print(f"Search terms: {', '.join(summary.get('search_terms', []))}")
        print(f"Fetched rows: {summary.get('fetched_rows', 0)}")
        print(f"Added: {summary.get('added', 0)}")
        print(f"Updated: {summary.get('updated', 0)}")
        print(f"Total cached posts: {summary.get('total', 0)}")
        print("Next: cv posts fit")
        return 0

    if action == "fit":
        if not posts:
            print("No cached posts yet.")
            print("Run: cv posts fetch")
            return 0

        config = load_auto_config(root)
        summary = fit_cached_posts(root, state, config, posts, force=False)
        save_posts(path, posts)
        print("Posts fit complete.")
        print(f"Scored now: {summary.get('scored', 0)}")
        print(f"From cache: {summary.get('cached', 0)}")
        print(f"Accepted: {len(summary.get('accepted', []))}")
        print(f"Filtered out: {summary.get('filtered', 0)}")

        accepted_rows = summary.get("accepted", [])
        if accepted_rows:
            print()
            _print_rows(root, path, accepted_rows, len(posts))
        return 0

    posts = _sort_posts(posts)

    if not posts:
        print("No cached posts yet.")
        print("Run: cv posts fetch")
        return 0

    if action == "show":
        if len(args) < 2 or not args[1].isdigit():
            die("Usage: cv posts show <index>")
        idx = int(args[1])
        if idx < 1 or idx > len(posts):
            die(f"Index out of range. Available: 1..{len(posts)}")

        row = posts[idx - 1]
        print(f"Index: {idx}")
        print(f"URL: {row.get('url', '')}")
        print(f"Company: {row.get('company', '')}")
        print(f"Title: {row.get('title', '')}")
        print(f"Status: {row.get('status', '')}")
        print(f"Fit: {row.get('fit_score', 0)}/100 ({row.get('grade', 'D')})")
        print(f"Apply status: {row.get('apply_status', '')}")
        print(f"Apply detail: {row.get('apply_detail', '')}")
        print(f"Tracked item: {row.get('track_item', '')}")
        print(f"Updated: {row.get('updated_at', '')}")
        print("Matched tags: " + ", ".join(row.get("matched_tags", [])[:25]))
        print("Missing tags: " + ", ".join(row.get("missing_tags", [])[:25]))
        snippet = str(row.get("summary_snippet", ""))
        if snippet:
            print("Snippet:")
            print(snippet)
        return 0

    mode = action
    if mode in {"list", "accepted"}:
        rows = [row for row in posts if str(row.get("status", "")) == "accepted"]
    elif mode == "filtered":
        rows = [row for row in posts if str(row.get("status", "")) == "filtered"]
    elif mode == "all":
        rows = posts
    else:
        die(USAGE_POSTS)

    _print_rows(root, path, rows, len(posts))
    return 0
