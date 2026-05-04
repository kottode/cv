from __future__ import annotations

from pathlib import Path
from typing import Any

from ...config import AutoConfig, CVState
from ...errors import CVError, die, warn
from ...internal.auto_config import auto_config_file, load_auto_config, save_auto_config
from ...internal import browser, telegram
from ...internal.ats import ats_enrichment_text, run_external_ats_parser
from ...internal.filters import default_filter_name, load_filter_profile
from ...internal.posts_db import update_post_apply_tracking
from ...internal.project import ensure_resume_exists, extract_section_body, load_state, read_text, require_project
from ...internal.posts_pipeline import best_effort_apply, fetch_posts_from_jobspy, fit_cached_posts
from ...internal.scheduler import (
    disable_hourly_auto_schedule,
    enable_hourly_auto_schedule,
    has_hourly_auto_schedule,
    next_hourly_auto_run,
)
from ...internal.resume_analysis import build_tags_from_resume, extract_meaningful_tags, merge_unique_tags, parse_experience_entries
from ...strings import USAGE_AUTO
from ...utils import now_iso
from ..posts.api import ensure_posts_file, load_posts
from ..track.api import ensure_track_file, upsert_item


def _print_search_urls(urls: list[str]) -> None:
    cleaned = [str(url).strip() for url in urls if str(url).strip()]
    if not cleaned:
        print("Search URLs: (none configured)")
        return
    print(f"Search URLs ({len(cleaned)}):")
    for url in cleaned:
        print(f"- {url}")

def notify(message: str) -> tuple[bool, str]:
    config = telegram.load_config()
    token = (config.get("bot_token") or "").strip()
    chat_id = (config.get("chat_id") or "").strip()
    if not token or not chat_id:
        return False, "telegram not configured"
    return telegram.send_message(token, chat_id, message[:4000])


def run_auto_pipeline(root: Path, state: CVState, config: AutoConfig) -> dict[str, Any]:
    resume = ensure_resume_exists(root, state)
    resume_text = read_text(resume)

    provider, parsed, hint = run_external_ats_parser(
        resume_text,
        auto_setup=False,
        extract_section_body=extract_section_body,
        parse_experience_entries=parse_experience_entries,
        extract_meaningful_tags=extract_meaningful_tags,
    )
    if hint:
        warn(hint)

    resume_tags = build_tags_from_resume(resume_text)
    ats_seed = ats_enrichment_text(parsed)
    if ats_seed:
        resume_tags = merge_unique_tags(resume_tags, extract_meaningful_tags(ats_seed, max_tags=35), limit=60)

    posts_path = ensure_posts_file(root, state)
    fetch_summary = fetch_posts_from_jobspy(root, state, config)
    profile_name = config.filter_profile or default_filter_name(state)
    profile = load_filter_profile(root, profile_name)
    setattr(config, "_active_profile", profile)
    fit_summary = fit_cached_posts(root, state, config, force=False)

    accepted_posts: list[dict[str, Any]] = fit_summary.get("accepted", [])
    track_path = ensure_track_file(root, state)

    apply_summary = best_effort_apply(
        accepted_posts,
        max_items=config.max_posts,
        auto_apply=config.auto_apply,
        apply_func=browser.attempt_auto_apply,
        upsert_track_item=lambda item, status: upsert_item(track_path, item, status),
        persist_post_update=lambda **kwargs: update_post_apply_tracking(root, state, **kwargs),
    )

    stored_count = int(fetch_summary.get("added", 0)) + int(fetch_summary.get("updated", 0))
    discovered_count = int(fetch_summary.get("fetched_rows", 0))
    parsed_count = int(fit_summary.get("scored", 0)) + int(fit_summary.get("cached", 0))
    filtered_count = int(fit_summary.get("filtered", 0))
    applied_count = int(apply_summary.get("applied", 0))
    tracked_count = int(apply_summary.get("tracked", 0))
    tracked_applied = int(apply_summary.get("tracked_applied", 0))
    tracked_rejected = int(apply_summary.get("tracked_rejected", 0))
    tracked_interview = int(apply_summary.get("tracked_interview", 0))
    tracked_offer = int(apply_summary.get("tracked_offer", 0))
    tracked_ghosted = int(apply_summary.get("tracked_ghosted", 0))

    for row in accepted_posts:
        row["ats_source"] = provider

    accepted_posts.sort(key=lambda row: int(row.get("fit_score", 0)), reverse=True)
    return {
        "posts_path": posts_path,
        "search_terms": fetch_summary.get("search_terms", []),
        "search_urls": fetch_summary.get("search_urls", []),
        "discovered": discovered_count,
        "parsed": parsed_count,
        "filtered": filtered_count,
        "stored": stored_count,
        "applied": applied_count,
        "tracked": tracked_count,
        "tracked_applied": tracked_applied,
        "tracked_rejected": tracked_rejected,
        "tracked_interview": tracked_interview,
        "tracked_offer": tracked_offer,
        "tracked_ghosted": tracked_ghosted,
        "total_posts": int(fit_summary.get("total", 0)),
        "accepted": accepted_posts,
        "ats_source": provider,
        "filter_profile": profile_name,
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
        posts = load_posts(root, state)
        accepted = sum(1 for row in posts if str(row.get("status", "")) == "accepted")
        filtered = sum(1 for row in posts if str(row.get("status", "")) == "filtered")
        scheduled = has_hourly_auto_schedule()
        print("Automation status")
        print(f"Enabled: {'yes' if config.enabled else 'no'}")
        print(f"Hourly scheduler: {'enabled' if scheduled else 'disabled'}")
        print(f"Config: {config_path.relative_to(root)}")
        print(f"Search terms: {len(config.search_terms)}")
        _print_search_urls(config.search_urls)
        print(f"Job sites: {', '.join(config.job_sites)}")
        print(f"Search location: {config.search_location}")
        print(f"Results wanted: {config.results_wanted}")
        print(f"Filter profile: {config.filter_profile or default_filter_name(state)}")
        print(f"Min fit score: {config.min_score}")
        print(f"Max parsed posts per run: {config.max_posts}")
        print(f"Auto apply: {'yes' if config.auto_apply else 'no'}")
        print(f"Telegram notify: {'yes' if config.notify else 'no'}")
        print(f"Posts store: {posts_path.relative_to(root)}")
        print(f"Stored posts: {len(posts)} (accepted={accepted}, filtered={filtered})")
        print(f"Last run: {config.last_run_at or 'never'}")
        if scheduled:
            print(f"Next scheduled run: {next_hourly_auto_run()}")
        else:
            print("Next scheduled run: not scheduled")
        if config.last_error:
            print(f"Last error: {config.last_error}")
        if not config.search_terms:
            print("Hint: set AUTO_SEARCH_TERMS in .cv/auto.env (comma-separated terms).")
        return 0

    if action == "disable":
        config.enabled = False
        save_auto_config(root, config)
        print("Automation disabled.")
        print(f"Config: {config_path.relative_to(root)}")
        return 0

    if action == "schedule":
        cron_line = enable_hourly_auto_schedule()
        print("Hourly automation scheduler enabled.")
        print("Runs at minute 0 every hour.")
        print(f"Next scheduled run: {next_hourly_auto_run()}")
        print(f"Cron: {cron_line}")
        return 0

    if action in {"unschedule", "schedule-off"}:
        removed = disable_hourly_auto_schedule()
        if removed:
            print("Hourly automation scheduler disabled.")
        else:
            print("Hourly automation scheduler was already disabled.")
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
        print(f"Tracked updates: {summary.get('tracked', 0)}")
        print(
            "Tracked status counts: "
            f"applied={summary.get('tracked_applied', 0)} "
            f"rejected={summary.get('tracked_rejected', 0)} "
            f"interview={summary.get('tracked_interview', 0)} "
            f"offer={summary.get('tracked_offer', 0)} "
            f"ghosted={summary.get('tracked_ghosted', 0)}"
        )
        print(f"Posts file: {posts_path.relative_to(root)}")
        print(f"ATS source used: {summary.get('ats_source', '')}")
        print(f"Filter profile used: {summary.get('filter_profile', config.filter_profile or default_filter_name(state))}")
        _print_search_urls(summary.get("search_urls", config.search_urls))

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
                f"Fetched {summary.get('discovered', 0)} jobs, "
                f"Applied to {summary.get('applied', 0)} (total: {summary.get('total_posts', 0)})"
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
