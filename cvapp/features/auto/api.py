from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from ...config import AutoConfig, CVState
from ...errors import CVError, die, warn
from ...internal.auto_config import auto_config_file, load_auto_config, save_auto_config
from ...internal import browser, telegram, web
from ...internal.ats import ats_enrichment_text, run_external_ats_parser
from ...internal.project import ensure_resume_exists, load_state, read_text, require_project
from ...internal.resume_analysis import (
    build_post_item_label,
    build_tags_from_resume,
    extract_meaningful_tags,
    infer_company_from_url,
    infer_title_from_text_and_url,
    merge_unique_tags,
)
from ...strings import USAGE_AUTO
from ...utils import now_iso
from ..fit.api import analyze_job_fit, keyword_filter_reason
from ..posts.api import ensure_posts_file, load_posts, save_posts, upsert_post_record
from ..track.api import ensure_track_file, upsert_item

def notify(message: str) -> tuple[bool, str]:
    config = telegram.load_config()
    token = (config.get("bot_token") or "").strip()
    chat_id = (config.get("chat_id") or "").strip()
    if not token or not chat_id:
        return False, "telegram not configured"
    return telegram.send_message(token, chat_id, message[:4000])


def run_auto_pipeline(root: Path, state: CVState, config: AutoConfig) -> dict[str, Any]:
    if not config.search_urls:
        die("No AUTO_SEARCH_URLS configured. Edit .cv/auto.env or set CV_AUTO_SEARCH_URLS.")

    resume = ensure_resume_exists(root, state)
    resume_text = read_text(resume)

    provider, parsed, hint = run_external_ats_parser(resume_text, auto_setup=False)
    if hint:
        warn(hint)

    resume_tags = build_tags_from_resume(resume_text)
    ats_seed = ats_enrichment_text(parsed)
    if ats_seed:
        resume_tags = merge_unique_tags(resume_tags, extract_meaningful_tags(ats_seed, max_tags=35), limit=60)
    resume_keywords = set(resume_tags)

    posts_path = ensure_posts_file(root, state)
    posts = load_posts(posts_path)

    discovered_urls: list[str] = []
    seen_urls: set[str] = set()
    for seed in config.search_urls:
        seed = seed.strip()
        if not seed:
            continue
        for url in web.discover_job_urls(seed, config.max_links_per_seed):
            normalized = web.normalize_url(url)
            if not normalized or normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            discovered_urls.append(normalized)

    parsed_count = 0
    filtered_count = 0
    stored_count = 0
    applied_count = 0
    accepted_posts: list[dict[str, Any]] = []
    track_path = ensure_track_file(root, state)

    for url in discovered_urls:
        if parsed_count >= config.max_posts:
            break

        try:
            job_text = web.extract_primary_text(url)
        except CVError as exc:
            warn(f"auto: failed to parse {url}: {exc}")
            continue

        normalized_text = re.sub(r"\s+", " ", job_text).strip()
        if len(normalized_text) < 60:
            continue
        if len(normalized_text) > 20000:
            normalized_text = normalized_text[:20000]

        parsed_count += 1

        company = infer_company_from_url(url)
        title = infer_title_from_text_and_url(job_text, url)
        analysis = analyze_job_fit(normalized_text, resume_keywords)
        filter_reason = keyword_filter_reason(normalized_text, config.include_keywords, config.exclude_keywords)
        accepted = analysis["score"] >= config.min_score and not filter_reason

        apply_status = "not-attempted"
        apply_detail = ""
        applied_at = ""
        track_item = ""

        if accepted and config.auto_apply:
            apply_status, apply_detail = browser.attempt_auto_apply(url)
            if apply_status == "applied":
                applied_at = now_iso()
                track_item = build_post_item_label(company, title)
                upsert_item(track_path, track_item, "applied")
                applied_count += 1

        if not accepted:
            filtered_count += 1

        now = now_iso()
        record: dict[str, Any] = {
            "id": hashlib.sha1(url.encode("utf-8")).hexdigest()[:12],
            "url": url,
            "company": company,
            "title": title,
            "status": "accepted" if accepted else "filtered",
            "filter_reason": filter_reason,
            "fit_score": analysis["score"],
            "grade": analysis["grade"],
            "job_tags": analysis["job_tags"][:60],
            "matched_tags": analysis["matched_tags"][:30],
            "missing_tags": analysis["missing_tags"][:30],
            "summary_snippet": normalized_text[:260],
            "updated_at": now,
            "discovered_at": now,
            "apply_status": apply_status,
            "apply_detail": apply_detail,
            "applied_at": applied_at,
            "track_item": track_item,
            "ats_source": provider,
        }

        upsert_post_record(posts, record)
        stored_count += 1
        if accepted:
            accepted_posts.append(record)

    save_posts(posts_path, posts)

    accepted_posts.sort(key=lambda row: int(row.get("fit_score", 0)), reverse=True)
    return {
        "posts_path": posts_path,
        "discovered": len(discovered_urls),
        "parsed": parsed_count,
        "filtered": filtered_count,
        "stored": stored_count,
        "applied": applied_count,
        "accepted": accepted_posts,
        "ats_source": provider,
    }


def cmd_auto(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    ensure_resume_exists(root, state)

    action = args[0].strip().lower() if args else "status"
    config = load_auto_config(root)
    config_path = auto_config_file(root)
    posts_path = ensure_posts_file(root, state)

    if not config_path.is_file():
        save_auto_config(root, config)

    if action == "status":
        posts = load_posts(posts_path)
        accepted = sum(1 for row in posts if str(row.get("status", "")) == "accepted")
        filtered = sum(1 for row in posts if str(row.get("status", "")) == "filtered")
        print("Automation status")
        print(f"Enabled: {'yes' if config.enabled else 'no'}")
        print(f"Config: {config_path.relative_to(root)}")
        print(f"Search seeds: {len(config.search_urls)}")
        print(f"Min fit score: {config.min_score}")
        print(f"Max parsed posts per run: {config.max_posts}")
        print(f"Auto apply: {'yes' if config.auto_apply else 'no'}")
        print(f"Telegram notify: {'yes' if config.notify else 'no'}")
        print(f"Posts store: {posts_path.relative_to(root)}")
        print(f"Stored posts: {len(posts)} (accepted={accepted}, filtered={filtered})")
        print(f"Last run: {config.last_run_at or 'never'}")
        if config.last_error:
            print(f"Last error: {config.last_error}")
        if not config.search_urls:
            print("Hint: set AUTO_SEARCH_URLS in .cv/auto.env (comma-separated URLs)")
        return 0

    if action == "disable":
        config.enabled = False
        save_auto_config(root, config)
        print("Automation disabled.")
        print(f"Config: {config_path.relative_to(root)}")
        return 0

    if action == "enable":
        config.enabled = True
        save_auto_config(root, config)

        try:
            summary = run_auto_pipeline(root, state, config)
            config.last_error = ""
        except CVError as exc:
            config.last_run_at = now_iso()
            config.last_error = str(exc)
            save_auto_config(root, config)
            die(str(exc))

        config.last_run_at = now_iso()
        config.last_seeked = int(summary.get("discovered", 0))
        config.last_parsed = int(summary.get("parsed", 0))
        config.last_filtered = int(summary.get("filtered", 0))
        config.last_stored = int(summary.get("stored", 0))
        config.last_applied = int(summary.get("applied", 0))
        save_auto_config(root, config)

        print("Automation enabled.")
        print(f"Discovered URLs: {summary.get('discovered', 0)}")
        print(f"Parsed posts: {summary.get('parsed', 0)}")
        print(f"Filtered out: {summary.get('filtered', 0)}")
        print(f"Stored/updated: {summary.get('stored', 0)}")
        print(f"Auto-applied: {summary.get('applied', 0)}")
        print(f"Posts file: {posts_path.relative_to(root)}")
        print(f"ATS source used: {summary.get('ats_source', '')}")

        accepted: list[dict[str, Any]] = summary.get("accepted", [])
        if accepted:
            print("Top accepted:")
            for row in accepted[:5]:
                print(f"- {row.get('grade', 'D')} {row.get('fit_score', 0)}/100 | {row.get('company', '')} | {row.get('title', '')}")

        if config.notify:
            top = accepted[:3]
            top_lines = [
                f"- {row.get('grade', 'D')} {row.get('fit_score', 0)}/100 {row.get('company', '')} | {row.get('title', '')}"
                for row in top
            ]
            summary_message = (
                f"cv auto run ({state.current_job})\n"
                f"discovered={summary.get('discovered', 0)} parsed={summary.get('parsed', 0)} "
                f"filtered={summary.get('filtered', 0)} stored={summary.get('stored', 0)} applied={summary.get('applied', 0)}"
            )
            if top_lines:
                summary_message += "\n" + "\n".join(top_lines)
            ok, detail = notify(summary_message)
            if ok:
                print("Telegram notification sent.")
            else:
                warn(f"Telegram notification skipped: {detail}")
        return 0

    die(USAGE_AUTO)
    return 1
