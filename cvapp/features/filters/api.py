from __future__ import annotations

from ...internal.auto_config import load_auto_config, save_auto_config
from ...internal.filters import (
    default_filter_name,
    list_filter_profiles,
    load_filter_profile,
    save_filter_profile,
)
from ...internal.project import load_state, require_project


def _prompt_list(prompt: str, current: list[str]) -> list[str]:
    current_text = ",".join(current)
    value = input(f"{prompt} [{current_text}]: ").strip()
    if not value:
        return current
    return [token.strip().lower() for token in value.split(",") if token.strip()]


def _prompt_bool(prompt: str, current: bool) -> bool:
    suffix = "Y/n" if current else "y/N"
    raw = input(f"{prompt} ({suffix}): ").strip().lower()
    if not raw:
        return current
    return raw in {"y", "yes", "1", "true", "on"}


def _prompt_text(prompt: str, current: str) -> str:
    value = input(f"{prompt} [{current}]: ").strip()
    if not value:
        return current
    return value


def _prompt_int(prompt: str, current: int) -> int:
    raw = input(f"{prompt} [{current}]: ").strip()
    if not raw:
        return current
    try:
        return max(0, int(raw))
    except Exception:
        return current


def cmd_filters(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    config = load_auto_config(root)

    if args and args[0].lower() == "list":
        names = list_filter_profiles(root)
        print("Filter profiles:")
        if not names:
            print(" (none)")
            return 0
        for name in names:
            marker = "*" if name == (config.filter_profile or default_filter_name(state)) else " "
            print(f" {marker} {name}")
        return 0

    requested = args[0] if args else (config.filter_profile or default_filter_name(state))
    profile = load_filter_profile(root, requested)

    print(f"Editing filter profile: {profile['name']}")
    profile["seniority"] = _prompt_list("Seniority tokens (comma-separated)", profile.get("seniority", []))
    profile["locations"] = _prompt_list("Preferred locations (comma-separated)", profile.get("locations", []))
    profile["accept_remote"] = _prompt_bool("Accept remote jobs", bool(profile.get("accept_remote", True)))
    profile["phone"] = _prompt_text("Phone", str(profile.get("phone", "")))
    profile["email"] = _prompt_text("Email", str(profile.get("email", "")))
    profile["salary_min"] = _prompt_int("Minimum salary per month in $ (integer)", int(profile.get("salary_min", 0) or 0))
    profile["job_types"] = _prompt_list("Job types (comma-separated, e.g. full-time,contract)", profile.get("job_types", []))

    path = save_filter_profile(root, profile)
    config.filter_profile = str(profile.get("name", ""))
    save_auto_config(root, config)

    print(f"Saved filter profile: {path.relative_to(root)}")
    print(f"Active filter profile: {config.filter_profile}")
    return 0
