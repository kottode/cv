from __future__ import annotations

import hashlib
import random
import re
import time
from pathlib import Path
from typing import Any

from ..config import AutoConfig, CVState
from ..errors import CVError, warn
from ..utils import now_iso
from . import web
from .filters import filter_signature, profile_filter_reason
from .jobspy import fetch_jobs
from .posts_db import load_fit_cache, load_posts, upsert_fit_cache, upsert_fetched_posts
from .project import ensure_resume_exists, read_text
from .resume_analysis import (
    analyze_job_fit,
    build_post_item_label,
    build_tags_from_resume,
    extract_meaningful_tags,
    keyword_filter_reason,
)


_MIN_APPLY_COOLDOWN_SEC = 7.0
_MAX_APPLY_COOLDOWN_SEC = 19.0


def _resume_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def resume_hash_for_state(root: Path, state: CVState) -> str:
    resume_path = ensure_resume_exists(root, state)
    resume_text = read_text(resume_path)
    return _resume_hash(resume_text)


def _score_from_row(row: dict[str, Any]) -> int:
    value = row.get("fit_score", 0)
    try:
        return int(value)
    except Exception:
        return 0


def _job_text_from_post(post: dict[str, Any]) -> str:
    description = str(post.get("description", "")).strip()
    if description:
        return description
    snippet = str(post.get("summary_snippet", "")).strip()
    if snippet:
        return snippet
    url = str(post.get("url", "")).strip()
    if not url:
        return ""
    try:
        return web.extract_primary_text(url)
    except CVError as exc:
        warn(f"posts: failed to parse {url}: {exc}")
        return ""


def _derive_track_status(apply_status: str, apply_detail: str) -> str | None:
    status = (apply_status or "").strip().lower()
    detail = (apply_detail or "").strip().lower()

    # Explicit handling for core tracking states.
    if status == "applied":
        return "applied"
    if status in {"rejected", "reject"} or "reject" in detail:
        return "rejected"
    if status in {"offer", "offered"} or "offer" in detail:
        return "offer"
    if status.startswith("interview") or "interview" in detail:
        return "interview1"
    if status == "ghosted" or "ghosted" in detail:
        return "ghosted"
    return None


def fetch_posts_from_jobspy(root: Path, state: CVState, config: AutoConfig) -> dict[str, Any]:
    search_terms = [term.strip() for term in config.search_terms if term.strip()]
    if not search_terms:
        title_term = (state.current_title or "").strip()
        if title_term:
            search_terms = [title_term]
        else:
            search_terms = [state.current_job.replace("-", " ").strip()]
    search_terms = [term for term in search_terms if term]

    fetched_rows = fetch_jobs(
        search_terms=search_terms,
        sites=config.job_sites,
        location=config.search_location,
        results_wanted=config.results_wanted,
    )
    summary = upsert_fetched_posts(root, state, fetched_rows, source="jobspy")
    summary["search_terms"] = search_terms
    summary["search_urls"] = [str(url).strip() for url in config.search_urls if str(url).strip()]
    summary["fetched_rows"] = len(fetched_rows)
    return summary


def fit_cached_posts(
    root: Path,
    state: CVState,
    config: AutoConfig,
    *,
    force: bool = False,
) -> dict[str, Any]:
    posts = load_posts(root, state)
    resume_path = ensure_resume_exists(root, state)
    resume_text = read_text(resume_path)
    resume_tags = build_tags_from_resume(resume_text)

    resume_hash = _resume_hash(resume_text)
    profile = getattr(config, "_active_profile", {}) or {}
    cache_key = f"{resume_hash}:{filter_signature(profile)}"
    resume_keywords = set(resume_tags)
    fit_cache = {} if force else load_fit_cache(root, state, cache_key)

    scored = 0
    cached = 0
    filtered = 0
    accepted: list[dict[str, Any]] = []
    fit_entries: list[dict[str, Any]] = []
    now = now_iso()

    for row in posts:
        uid = str(row.get("uid", "")).strip()
        cached_entry = fit_cache.get(uid)
        if cached_entry:
            merged_row = dict(row)
            merged_row.update(cached_entry)
            cached += 1
            if str(merged_row.get("status", "")) == "accepted":
                accepted.append(merged_row)
            elif str(merged_row.get("status", "")) == "filtered":
                filtered += 1
            continue

        job_text = _job_text_from_post(row)
        normalized_text = re.sub(r"\s+", " ", job_text).strip()
        if not normalized_text:
            fit_entries.append(
                {
                    "uid": uid,
                    "status": "filtered",
                    "filter_reason": "missing-job-text",
                    "fit_score": 0,
                    "grade": "D",
                    "matched_tags": [],
                    "missing_tags": [],
                    "job_tags": [],
                    "updated_at": now,
                }
            )
            scored += 1
            filtered += 1
            continue

        if len(normalized_text) > 30000:
            normalized_text = normalized_text[:30000]

        analysis = analyze_job_fit(normalized_text, resume_keywords)
        filter_reason = keyword_filter_reason(normalized_text, config.include_keywords, config.exclude_keywords)
        if not filter_reason:
            filter_reason = profile_filter_reason(profile, row, normalized_text)
        is_accepted = int(analysis["score"]) >= config.min_score and not filter_reason

        fit_entry = {
            "uid": uid,
            "status": "accepted" if is_accepted else "filtered",
            "filter_reason": filter_reason,
            "fit_score": int(analysis["score"]),
            "grade": str(analysis["grade"]),
            "job_tags": extract_meaningful_tags(normalized_text, max_tags=60),
            "matched_tags": list(analysis["matched_tags"][:30]),
            "missing_tags": list(analysis["missing_tags"][:30]),
            "updated_at": now,
        }
        fit_entries.append(fit_entry)

        merged_row = dict(row)
        merged_row.update(fit_entry)

        if is_accepted:
            accepted.append(merged_row)
        else:
            filtered += 1

        scored += 1

    upsert_fit_cache(root, state, cache_key, fit_entries)
    accepted.sort(key=_score_from_row, reverse=True)

    return {
        "resume_hash": resume_hash,
        "scored": scored,
        "cached": cached,
        "accepted": accepted,
        "filtered": filtered,
        "total": len(posts),
    }


def best_effort_apply(
    posts: list[dict[str, Any]],
    *,
    max_items: int,
    auto_apply: bool,
    apply_func,
    upsert_track_item,
    persist_post_update,
) -> dict[str, int]:
    if not auto_apply:
        return {"attempted": 0, "applied": 0, "tracked": 0}

    attempted = 0
    applied = 0
    tracked = 0
    status_counts = {
        "applied": 0,
        "rejected": 0,
        "interview1": 0,
        "offer": 0,
        "ghosted": 0,
    }
    for row in posts:
        if str(row.get("status", "")) != "accepted":
            continue
        if attempted >= max_items:
            break

        if attempted > 0:
            time.sleep(random.uniform(_MIN_APPLY_COOLDOWN_SEC, _MAX_APPLY_COOLDOWN_SEC))

        url = str(row.get("url", "")).strip()
        if not url:
            continue

        status, detail = apply_func(url)
        uid = str(row.get("uid", "")).strip()
        row["apply_status"] = status
        row["apply_detail"] = detail
        row["updated_at"] = now_iso()
        attempted += 1
        item = build_post_item_label(str(row.get("company", "")), str(row.get("title", "")))
        row["track_item"] = item

        track_status = _derive_track_status(status, detail)
        if track_status is not None:
            if not row.get("applied_at"):
                row["applied_at"] = now_iso()

            tracked_row = upsert_track_item(item, track_status)
            row["track_status"] = str(tracked_row.get("status", track_status))
            tracked += 1

            if track_status == "applied":
                applied += 1
            if track_status in status_counts:
                status_counts[track_status] += 1

        if uid:
            persist_post_update(
                uid=uid,
                apply_status=str(row.get("apply_status", "")),
                apply_detail=str(row.get("apply_detail", "")),
                applied_at=str(row.get("applied_at", "")),
                track_item=str(row.get("track_item", "")),
                track_status=str(row.get("track_status", "")),
                updated_at=str(row.get("updated_at", now_iso())),
            )

    return {
        "attempted": attempted,
        "applied": applied,
        "tracked": tracked,
        "tracked_applied": status_counts["applied"],
        "tracked_rejected": status_counts["rejected"],
        "tracked_interview": status_counts["interview1"],
        "tracked_offer": status_counts["offer"],
        "tracked_ghosted": status_counts["ghosted"],
    }
