from __future__ import annotations

from pathlib import Path
from typing import Any

from ...config import AutoConfig, CVState
from ...errors import CVError, die, warn
from ...internal.auto_config import auto_config_file, load_auto_config, save_auto_config
from ...internal import browser, telegram
from ...internal.ats import ats_enrichment_text, run_external_ats_parser
from ...internal.project import ensure_resume_exists, load_state, read_text, require_project
from ...internal.posts_pipeline import best_effort_apply, fetch_posts_from_jobspy, fit_cached_posts
from ...internal.resume_analysis import build_tags_from_resume, extract_meaningful_tags, merge_unique_tags
from ...strings import USAGE_AUTO
from ...utils import now_iso
from ..posts.api import ensure_posts_file, load_posts, save_posts
from ..track.api import ensure_track_file, upsert_item

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

    provider, parsed, hint = run_external_ats_parser(resume_text, auto_setup=False)
    if hint:
        warn(hint)

    resume_tags = build_tags_from_resume(resume_text)
    ats_seed = ats_enrichment_text(parsed)
    if ats_seed:
        resume_tags = merge_unique_tags(resume_tags, extract_meaningful_tags(ats_seed, max_tags=35), limit=60)

    posts_path = ensure_posts_file(root, state)
    posts = load_posts(posts_path)
    fetch_summary = fetch_posts_from_jobspy(root, state, config, posts)
    fit_summary = fit_cached_posts(root, state, config, posts, force=False)

    accepted_posts: list[dict[str, Any]] = fit_summary.get("accepted", [])
    track_path = ensure_track_file(root, state)

    apply_summary = best_effort_apply(
        accepted_posts,
        max_items=config.max_posts,
        auto_apply=config.auto_apply,
        apply_func=browser.attempt_auto_apply,
        upsert_track_item=lambda item, status: upsert_item(track_path, item, status),
    )

    stored_count = int(fetch_summary.get("added", 0)) + int(fetch_summary.get("updated", 0))
    discovered_count = int(fetch_summary.get("fetched_rows", 0))
    parsed_count = int(fit_summary.get("scored", 0)) + int(fit_summary.get("cached", 0))
    filtered_count = int(fit_summary.get("filtered", 0))
    applied_count = int(apply_summary.get("applied", 0))

    for row in accepted_posts:
        row["ats_source"] = provider

    save_posts(posts_path, posts)

    accepted_posts.sort(key=lambda row: int(row.get("fit_score", 0)), reverse=True)
    return {
        "posts_path": posts_path,
        "discovered": discovered_count,
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
        print(f"Search terms: {len(config.search_terms)}")
        print(f"Job sites: {', '.join(config.job_sites)}")
        print(f"Search location: {config.search_location}")
        print(f"Results wanted: {config.results_wanted}")
        print(f"Min fit score: {config.min_score}")
        print(f"Max parsed posts per run: {config.max_posts}")
        print(f"Auto apply: {'yes' if config.auto_apply else 'no'}")
        print(f"Telegram notify: {'yes' if config.notify else 'no'}")
        print(f"Posts store: {posts_path.relative_to(root)}")
        print(f"Stored posts: {len(posts)} (accepted={accepted}, filtered={filtered})")
        print(f"Last run: {config.last_run_at or 'never'}")
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
