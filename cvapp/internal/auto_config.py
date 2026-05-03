from __future__ import annotations

import os
from pathlib import Path

from ..config import AUTO_CONFIG_FILE, AutoConfig
from ..utils import quote_env
from .env import load_env_style_file, parse_env_bool, parse_env_int, parse_env_list


def auto_config_file(root: Path) -> Path:
    return root / AUTO_CONFIG_FILE


def load_auto_config(root: Path) -> AutoConfig:
    path = auto_config_file(root)
    values = load_env_style_file(path)

    env_search = parse_env_list(os.environ.get("CV_AUTO_SEARCH_URLS", ""))
    return AutoConfig(
        enabled=parse_env_bool(values.get("AUTO_ENABLED", "0"), default=False),
        search_urls=parse_env_list(values.get("AUTO_SEARCH_URLS", "")) or env_search,
        include_keywords=parse_env_list(values.get("AUTO_INCLUDE_KEYWORDS", "")),
        exclude_keywords=parse_env_list(values.get("AUTO_EXCLUDE_KEYWORDS", "")),
        min_score=parse_env_int(values.get("AUTO_MIN_SCORE", "60"), default=60, minimum=0, maximum=100),
        max_posts=parse_env_int(values.get("AUTO_MAX_POSTS", "12"), default=12, minimum=1, maximum=200),
        max_links_per_seed=parse_env_int(
            values.get("AUTO_MAX_LINKS_PER_SEED", "25"),
            default=25,
            minimum=1,
            maximum=200,
        ),
        auto_apply=parse_env_bool(values.get("AUTO_APPLY", "1"), default=True),
        notify=parse_env_bool(values.get("AUTO_NOTIFY", "1"), default=True),
        last_run_at=(values.get("AUTO_LAST_RUN_AT", "") or "").strip(),
        last_seeked=parse_env_int(values.get("AUTO_LAST_SEEKED", "0"), default=0, minimum=0, maximum=1000000),
        last_parsed=parse_env_int(values.get("AUTO_LAST_PARSED", "0"), default=0, minimum=0, maximum=1000000),
        last_filtered=parse_env_int(values.get("AUTO_LAST_FILTERED", "0"), default=0, minimum=0, maximum=1000000),
        last_stored=parse_env_int(values.get("AUTO_LAST_STORED", "0"), default=0, minimum=0, maximum=1000000),
        last_applied=parse_env_int(values.get("AUTO_LAST_APPLIED", "0"), default=0, minimum=0, maximum=1000000),
        last_error=(values.get("AUTO_LAST_ERROR", "") or "").strip(),
    )


def save_auto_config(root: Path, config: AutoConfig) -> Path:
    path = auto_config_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            "# cv automation settings",
            "# AUTO_SEARCH_URLS accepts comma-separated seed URLs.",
            f"AUTO_ENABLED={quote_env('1' if config.enabled else '0')}",
            f"AUTO_SEARCH_URLS={quote_env(','.join(config.search_urls))}",
            f"AUTO_INCLUDE_KEYWORDS={quote_env(','.join(config.include_keywords))}",
            f"AUTO_EXCLUDE_KEYWORDS={quote_env(','.join(config.exclude_keywords))}",
            f"AUTO_MIN_SCORE={quote_env(str(config.min_score))}",
            f"AUTO_MAX_POSTS={quote_env(str(config.max_posts))}",
            f"AUTO_MAX_LINKS_PER_SEED={quote_env(str(config.max_links_per_seed))}",
            f"AUTO_APPLY={quote_env('1' if config.auto_apply else '0')}",
            f"AUTO_NOTIFY={quote_env('1' if config.notify else '0')}",
            f"AUTO_LAST_RUN_AT={quote_env(config.last_run_at)}",
            f"AUTO_LAST_SEEKED={quote_env(str(config.last_seeked))}",
            f"AUTO_LAST_PARSED={quote_env(str(config.last_parsed))}",
            f"AUTO_LAST_FILTERED={quote_env(str(config.last_filtered))}",
            f"AUTO_LAST_STORED={quote_env(str(config.last_stored))}",
            f"AUTO_LAST_APPLIED={quote_env(str(config.last_applied))}",
            f"AUTO_LAST_ERROR={quote_env(config.last_error)}",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return path
