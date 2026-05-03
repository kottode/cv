from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ..config import AutoConfig, CVState
from ..errors import CVError, warn
from ..utils import now_iso
from . import web
from .jobspy import fetch_jobs
from .project import ensure_resume_exists, read_text
from .resume_analysis import (
    analyze_job_fit,
    build_post_item_label,
    build_tags_from_resume,
    extract_meaningful_tags,
    keyword_filter_reason,
)


def _resume_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


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


def merge_fetched_posts(
    posts: list[dict[str, Any]],
    fetched_rows: list[dict[str, Any]],
    *,
    source: str,
) -> dict[str, Any]:
    now = now_iso()
    index_by_url: dict[str, dict[str, Any]] = {}
    for row in posts:
        url = web.normalize_url(str(row.get("url", "")))
        if url:
            index_by_url[url] = row

    added = 0
    updated = 0
    imported = 0

    for fetched in fetched_rows:
        imported += 1
        url = web.normalize_url(str(fetched.get("url", "")))
        identity = url or str(fetched.get("external_id", "")).strip()
        if not identity:
            continue

        existing = index_by_url.get(url) if url else None
        company = str(fetched.get("company", "")).strip()
        title = str(fetched.get("title", "")).strip()
        description = str(fetched.get("description", "")).strip()
        summary_snippet = re.sub(r"\s+", " ", description).strip()[:260]

        if existing is None:
            post_id = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
            row: dict[str, Any] = {
                "id": post_id,
                "url": url,
                "company": company,
                "title": title,
                "location": str(fetched.get("location", "")).strip(),
                "description": description[:30000],
                "summary_snippet": summary_snippet,
                "status": "fetched",
                "fit_score": 0,
                "grade": "D",
                "job_tags": [],
                "matched_tags": [],
                "missing_tags": [],
                "filter_reason": "",
                "source": source,
                "source_site": str(fetched.get("source_site", "")).strip(),
                "search_term": str(fetched.get("search_term", "")).strip(),
                "updated_at": now,
                "discovered_at": now,
                "first_seen_at": now,
                "apply_status": "not-attempted",
                "apply_detail": "",
                "applied_at": "",
                "track_item": "",
            }
            posts.append(row)
            if url:
                index_by_url[url] = row
            added += 1
            continue

        existing["company"] = company or str(existing.get("company", ""))
        existing["title"] = title or str(existing.get("title", ""))
        existing["location"] = str(fetched.get("location", "")).strip() or str(existing.get("location", ""))
        if description:
            existing["description"] = description[:30000]
            existing["summary_snippet"] = summary_snippet
        existing["source"] = source
        existing["source_site"] = str(fetched.get("source_site", "")).strip() or str(existing.get("source_site", ""))
        existing["search_term"] = str(fetched.get("search_term", "")).strip() or str(existing.get("search_term", ""))
        existing["updated_at"] = now
        updated += 1

    return {
        "imported": imported,
        "added": added,
        "updated": updated,
        "total": len(posts),
    }


def fetch_posts_from_jobspy(root: Path, state: CVState, config: AutoConfig, posts: list[dict[str, Any]]) -> dict[str, Any]:
    search_terms = [term.strip() for term in config.search_terms if term.strip()]
    if not search_terms:
        search_terms = [state.current_job.replace("-", " ").strip()]
    search_terms = [term for term in search_terms if term]

    fetched_rows = fetch_jobs(
        search_terms=search_terms,
        sites=config.job_sites,
        location=config.search_location,
        results_wanted=config.results_wanted,
    )
    summary = merge_fetched_posts(posts, fetched_rows, source="jobspy")
    summary["search_terms"] = search_terms
    summary["fetched_rows"] = len(fetched_rows)
    return summary


def fit_cached_posts(
    root: Path,
    state: CVState,
    config: AutoConfig,
    posts: list[dict[str, Any]],
    *,
    force: bool = False,
) -> dict[str, Any]:
    resume_path = ensure_resume_exists(root, state)
    resume_text = read_text(resume_path)
    resume_tags = build_tags_from_resume(resume_text)

    resume_hash = _resume_hash(resume_text)
    resume_keywords = set(resume_tags)

    scored = 0
    cached = 0
    filtered = 0
    accepted: list[dict[str, Any]] = []
    now = now_iso()

    for row in posts:
        cached_hash = str(row.get("fit_resume_hash", "")).strip()
        if (not force) and cached_hash == resume_hash and str(row.get("status", "")) in {"accepted", "filtered"}:
            cached += 1
            if str(row.get("status", "")) == "accepted":
                accepted.append(row)
            elif str(row.get("status", "")) == "filtered":
                filtered += 1
            continue

        job_text = _job_text_from_post(row)
        normalized_text = re.sub(r"\s+", " ", job_text).strip()
        if not normalized_text:
            row["status"] = "filtered"
            row["filter_reason"] = "missing-job-text"
            row["fit_score"] = 0
            row["grade"] = "D"
            row["matched_tags"] = []
            row["missing_tags"] = []
            row["job_tags"] = []
            row["fit_resume_hash"] = resume_hash
            row["updated_at"] = now
            scored += 1
            filtered += 1
            continue

        if len(normalized_text) > 30000:
            normalized_text = normalized_text[:30000]

        analysis = analyze_job_fit(normalized_text, resume_keywords)
        filter_reason = keyword_filter_reason(normalized_text, config.include_keywords, config.exclude_keywords)
        is_accepted = int(analysis["score"]) >= config.min_score and not filter_reason

        row["summary_snippet"] = normalized_text[:260]
        row["status"] = "accepted" if is_accepted else "filtered"
        row["filter_reason"] = filter_reason
        row["fit_score"] = int(analysis["score"])
        row["grade"] = str(analysis["grade"])
        row["job_tags"] = extract_meaningful_tags(normalized_text, max_tags=60)
        row["matched_tags"] = list(analysis["matched_tags"][:30])
        row["missing_tags"] = list(analysis["missing_tags"][:30])
        row["fit_resume_hash"] = resume_hash
        row["updated_at"] = now

        if is_accepted:
            accepted.append(row)
        else:
            filtered += 1

        scored += 1

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
) -> dict[str, int]:
    if not auto_apply:
        return {"attempted": 0, "applied": 0}

    attempted = 0
    applied = 0
    for row in posts:
        if str(row.get("status", "")) != "accepted":
            continue
        if attempted >= max_items:
            break

        url = str(row.get("url", "")).strip()
        if not url:
            continue

        status, detail = apply_func(url)
        row["apply_status"] = status
        row["apply_detail"] = detail
        row["updated_at"] = now_iso()
        attempted += 1

        if status != "applied":
            continue

        row["applied_at"] = now_iso()
        item = build_post_item_label(str(row.get("company", "")), str(row.get("title", "")))
        row["track_item"] = item
        upsert_track_item(item, "applied")
        applied += 1

    return {"attempted": attempted, "applied": applied}
