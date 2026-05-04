from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from ..config import STATE_DIR, CVState
from ..utils import now_iso


POSTS_DB_FILE = STATE_DIR / "posts.db"


def posts_db_path(root: Path) -> Path:
    return root / POSTS_DB_FILE


def ensure_posts_db(root: Path) -> Path:
    path = posts_db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                uid TEXT PRIMARY KEY,
                job TEXT NOT NULL,
                normalized_url TEXT NOT NULL,
                url TEXT NOT NULL,
                company TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                summary_snippet TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                source_site TEXT NOT NULL DEFAULT '',
                search_term TEXT NOT NULL DEFAULT '',
                overall_grade TEXT NOT NULL DEFAULT 'U',
                apply_status TEXT NOT NULL DEFAULT 'not-attempted',
                apply_detail TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL DEFAULT '',
                track_item TEXT NOT NULL DEFAULT '',
                track_status TEXT NOT NULL DEFAULT '',
                discovered_at TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(job, normalized_url)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS post_fit_cache (
                job TEXT NOT NULL,
                uid TEXT NOT NULL,
                resume_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                filter_reason TEXT NOT NULL DEFAULT '',
                fit_score INTEGER NOT NULL DEFAULT 0,
                grade TEXT NOT NULL DEFAULT 'D',
                job_tags TEXT NOT NULL DEFAULT '[]',
                matched_tags TEXT NOT NULL DEFAULT '[]',
                missing_tags TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (job, uid, resume_hash)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        migrated = conn.execute(
            "SELECT value FROM posts_meta WHERE key = 'legacy_json_migrated_v1'"
        ).fetchone()
        if migrated is None:
            _migrate_legacy_posts_json(root, conn)
            conn.execute(
                "INSERT OR REPLACE INTO posts_meta(key, value) VALUES('legacy_json_migrated_v1', '1')"
            )
        conn.commit()

    return path


def _migrate_legacy_posts_json(root: Path, conn: sqlite3.Connection) -> None:
    jobs_dir = root / "jobs"
    if not jobs_dir.is_dir():
        return

    for post_file in jobs_dir.glob("*/posts.json"):
        job = post_file.parent.name
        try:
            raw = post_file.read_text(encoding="utf-8").strip()
            payload = json.loads(raw) if raw else {}
        except Exception:
            continue

        if isinstance(payload, dict) and isinstance(payload.get("posts"), list):
            rows = payload.get("posts", [])
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []

        for item in rows:
            if not isinstance(item, dict):
                continue

            url = str(item.get("url", "")).strip()
            if not url:
                continue
            uid = _uid_for(job, url)
            updated_at = str(item.get("updated_at", "") or now_iso())
            first_seen_at = str(item.get("first_seen_at", "") or item.get("discovered_at", "") or updated_at)
            discovered_at = str(item.get("discovered_at", "") or first_seen_at)

            conn.execute(
                """
                INSERT OR IGNORE INTO posts (
                    uid, job, normalized_url, url, company, title, location, description, summary_snippet,
                    source, source_site, search_term, overall_grade,
                    apply_status, apply_detail, applied_at, track_item, track_status,
                    discovered_at, first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    job,
                    url,
                    url,
                    str(item.get("company", "")),
                    str(item.get("title", "")),
                    str(item.get("location", "")),
                    str(item.get("description", ""))[:30000],
                    str(item.get("summary_snippet", ""))[:260],
                    str(item.get("source", "legacy-json")),
                    str(item.get("source_site", "")),
                    str(item.get("search_term", "")),
                    str(item.get("grade", "U")),
                    str(item.get("apply_status", "not-attempted")),
                    str(item.get("apply_detail", "")),
                    str(item.get("applied_at", "")),
                    str(item.get("track_item", "")),
                    str(item.get("track_status", "")),
                    discovered_at,
                    first_seen_at,
                    updated_at,
                ),
            )

            resume_hash = str(item.get("fit_resume_hash", "")).strip()
            if not resume_hash:
                continue

            conn.execute(
                """
                INSERT OR REPLACE INTO post_fit_cache (
                    job, uid, resume_hash, status, filter_reason, fit_score, grade,
                    job_tags, matched_tags, missing_tags, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job,
                    uid,
                    resume_hash,
                    str(item.get("status", "fetched")),
                    str(item.get("filter_reason", "")),
                    _to_int(item.get("fit_score", 0), 0),
                    str(item.get("grade", "D")),
                    json.dumps(item.get("job_tags", []), ensure_ascii=True),
                    json.dumps(item.get("matched_tags", []), ensure_ascii=True),
                    json.dumps(item.get("missing_tags", []), ensure_ascii=True),
                    updated_at,
                ),
            )


def _uid_for(job: str, identity: str) -> str:
    return hashlib.sha1(f"{job}|{identity}".encode("utf-8")).hexdigest()[:16]
    
def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def upsert_fetched_posts(root: Path, state: CVState, fetched_rows: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
    path = ensure_posts_db(root)
    added = 0
    updated = 0
    imported = 0
    now = now_iso()

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        for fetched in fetched_rows:
            imported += 1
            normalized_url = str(fetched.get("url", "")).strip()
            identity = normalized_url or str(fetched.get("external_id", "")).strip()
            if not identity:
                continue
            if not normalized_url:
                normalized_url = identity

            uid = _uid_for(state.current_job, identity)
            company = str(fetched.get("company", "")).strip()
            title = str(fetched.get("title", "")).strip()
            location = str(fetched.get("location", "")).strip()
            description = str(fetched.get("description", "")).strip()[:30000]
            summary_snippet = " ".join(description.split())[:260]
            source_site = str(fetched.get("source_site", "")).strip()
            search_term = str(fetched.get("search_term", "")).strip()

            existing = conn.execute(
                "SELECT uid, company, title, location, first_seen_at, apply_status, apply_detail, applied_at, track_item, track_status, overall_grade "
                "FROM posts WHERE job = ? AND normalized_url = ?",
                (state.current_job, normalized_url),
            ).fetchone()

            if existing is None:
                conn.execute(
                    """
                    INSERT INTO posts (
                        uid, job, normalized_url, url, company, title, location, description, summary_snippet,
                        source, source_site, search_term, overall_grade,
                        apply_status, apply_detail, applied_at, track_item, track_status,
                        discovered_at, first_seen_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uid,
                        state.current_job,
                        normalized_url,
                        normalized_url,
                        company,
                        title,
                        location,
                        description,
                        summary_snippet,
                        source,
                        source_site,
                        search_term,
                        "U",
                        "not-attempted",
                        "",
                        "",
                        "",
                        "",
                        now,
                        now,
                        now,
                    ),
                )
                added += 1
                continue

            conn.execute(
                """
                UPDATE posts
                SET company = ?,
                    title = ?,
                    location = ?,
                    description = CASE WHEN ? <> '' THEN ? ELSE description END,
                    summary_snippet = CASE WHEN ? <> '' THEN ? ELSE summary_snippet END,
                    source = ?,
                    source_site = CASE WHEN ? <> '' THEN ? ELSE source_site END,
                    search_term = CASE WHEN ? <> '' THEN ? ELSE search_term END,
                    updated_at = ?
                WHERE uid = ?
                """,
                (
                    company or str(existing["company"] or ""),
                    title or str(existing["title"] or ""),
                    location or str(existing["location"] or ""),
                    description,
                    description,
                    summary_snippet,
                    summary_snippet,
                    source,
                    source_site,
                    source_site,
                    search_term,
                    search_term,
                    now,
                    str(existing["uid"]),
                ),
            )
            updated += 1

        total = int(
            conn.execute("SELECT COUNT(*) AS c FROM posts WHERE job = ?", (state.current_job,)).fetchone()[0]
        )
        conn.commit()

    return {
        "imported": imported,
        "added": added,
        "updated": updated,
        "total": total,
    }


def load_posts(root: Path, state: CVState) -> list[dict[str, Any]]:
    path = ensure_posts_db(root)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM posts WHERE job = ? ORDER BY updated_at DESC",
            (state.current_job,),
        ).fetchall()
    return [dict(row) for row in rows]


def load_fit_cache(root: Path, state: CVState, resume_hash: str) -> dict[str, dict[str, Any]]:
    path = ensure_posts_db(root)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM post_fit_cache WHERE job = ? AND resume_hash = ?",
            (state.current_job, resume_hash),
        ).fetchall()

    cache: dict[str, dict[str, Any]] = {}
    for row in rows:
        uid = str(row["uid"])
        cache[uid] = {
            "status": str(row["status"]),
            "filter_reason": str(row["filter_reason"]),
            "fit_score": int(row["fit_score"]),
            "grade": str(row["grade"]),
            "job_tags": json.loads(str(row["job_tags"] or "[]")),
            "matched_tags": json.loads(str(row["matched_tags"] or "[]")),
            "missing_tags": json.loads(str(row["missing_tags"] or "[]")),
            "updated_at": str(row["updated_at"]),
        }
    return cache


def upsert_fit_cache(root: Path, state: CVState, resume_hash: str, entries: list[dict[str, Any]]) -> None:
    if not entries:
        return

    path = ensure_posts_db(root)
    with sqlite3.connect(path) as conn:
        for entry in entries:
            conn.execute(
                """
                INSERT INTO post_fit_cache (
                    job, uid, resume_hash, status, filter_reason, fit_score, grade,
                    job_tags, matched_tags, missing_tags, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job, uid, resume_hash)
                DO UPDATE SET
                    status = excluded.status,
                    filter_reason = excluded.filter_reason,
                    fit_score = excluded.fit_score,
                    grade = excluded.grade,
                    job_tags = excluded.job_tags,
                    matched_tags = excluded.matched_tags,
                    missing_tags = excluded.missing_tags,
                    updated_at = excluded.updated_at
                """,
                (
                    state.current_job,
                    str(entry.get("uid", "")),
                    resume_hash,
                    str(entry.get("status", "fetched")),
                    str(entry.get("filter_reason", "")),
                    int(entry.get("fit_score", 0)),
                    str(entry.get("grade", "D")),
                    json.dumps(entry.get("job_tags", []), ensure_ascii=True),
                    json.dumps(entry.get("matched_tags", []), ensure_ascii=True),
                    json.dumps(entry.get("missing_tags", []), ensure_ascii=True),
                    str(entry.get("updated_at", now_iso())),
                ),
            )

            conn.execute(
                "UPDATE posts SET overall_grade = ?, updated_at = ? WHERE uid = ?",
                (str(entry.get("grade", "U")), str(entry.get("updated_at", now_iso())), str(entry.get("uid", ""))),
            )
        conn.commit()


def load_posts_with_fit(root: Path, state: CVState, resume_hash: str) -> list[dict[str, Any]]:
    posts = load_posts(root, state)
    cache = load_fit_cache(root, state, resume_hash)

    merged: list[dict[str, Any]] = []
    for row in posts:
        item = dict(row)
        fit = cache.get(str(item.get("uid", "")))
        if fit:
            item.update(fit)
        else:
            item.setdefault("status", "fetched")
            item.setdefault("filter_reason", "")
            item.setdefault("fit_score", 0)
            item.setdefault("grade", str(item.get("overall_grade", "U")))
            item.setdefault("job_tags", [])
            item.setdefault("matched_tags", [])
            item.setdefault("missing_tags", [])
        merged.append(item)

    merged.sort(key=lambda row: str(row.get("updated_at", "")), reverse=True)
    return merged


def update_post_apply_tracking(
    root: Path,
    state: CVState,
    uid: str,
    *,
    apply_status: str,
    apply_detail: str,
    applied_at: str,
    track_item: str,
    track_status: str,
    updated_at: str,
) -> None:
    path = ensure_posts_db(root)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            UPDATE posts
            SET apply_status = ?,
                apply_detail = ?,
                applied_at = ?,
                track_item = ?,
                track_status = ?,
                updated_at = ?
            WHERE job = ? AND uid = ?
            """,
            (
                apply_status,
                apply_detail,
                applied_at,
                track_item,
                track_status,
                updated_at,
                state.current_job,
                uid,
            ),
        )
        conn.commit()
