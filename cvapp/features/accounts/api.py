from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ...errors import die
from ...internal.project import require_project
from ...strings import USAGE_ACCOUNTS
from ...utils import now_iso, pretty_name


SUPPORTED_ACCOUNTS = {
    "linkedin": {
        "label": "LinkedIn",
        "login_url": "https://www.linkedin.com/login",
    },
    "indeed": {
        "label": "Indeed",
        "login_url": "https://secure.indeed.com/auth",
    },
    "glassdoor": {
        "label": "Glassdoor",
        "login_url": "https://www.glassdoor.com/profile/login_input.htm",
    },
    "ziprecruiter": {
        "label": "ZipRecruiter",
        "login_url": "https://www.ziprecruiter.com/login",
    },
    "greenhouse": {
        "label": "Greenhouse",
        "login_url": "https://boards.greenhouse.io/",
    },
    "lever": {
        "label": "Lever",
        "login_url": "https://jobs.lever.co/",
    },
    "workday": {
        "label": "Workday",
        "login_url": "https://www.myworkday.com/",
    },
}


def accounts_config_file(root: Path) -> Path:
    return root / ".cv" / "accounts.json"


def _default_browser_profile_dir(name: str) -> str:
    return str((Path.home() / ".local" / "share" / "cv" / "browser" / name).resolve())


def _default_account_record(name: str) -> dict[str, Any]:
    meta = SUPPORTED_ACCOUNTS.get(name, {})
    return {
        "name": name,
        "enabled": False,
        "label": str(meta.get("label") or pretty_name(name)),
        "login_url": str(meta.get("login_url") or ""),
        "username": "",
        "profile_url": "",
        "browser_profile_dir": _default_browser_profile_dir(name),
        "session_strategy": "persistent-profile",
        "mfa": "unknown",
        "manual_login_required": True,
        "notes": "",
        "updated_at": now_iso(),
    }


def _load_accounts(root: Path) -> dict[str, Any]:
    path = accounts_config_file(root)
    payload: dict[str, Any] = {"version": 1, "accounts": {}}
    if not path.is_file():
        return payload

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return payload

    if not isinstance(parsed, dict):
        return payload

    accounts = parsed.get("accounts")
    if not isinstance(accounts, dict):
        parsed["accounts"] = {}
    if "version" not in parsed:
        parsed["version"] = 1
    return parsed


def _save_accounts(root: Path, payload: dict[str, Any]) -> Path:
    path = accounts_config_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return path


def _prompt_text(label: str, current: str, *, required: bool = False) -> str:
    shown = current.strip()
    prompt = f"{label} [{shown}]: " if shown else f"{label}: "
    value = input(prompt).strip()
    if not value:
        value = shown
    if required and not value:
        die(f"{label} required")
    return value


def _prompt_bool(label: str, current: bool) -> bool:
    suffix = "Y/n" if current else "y/N"
    raw = input(f"{label} ({suffix}): ").strip().lower()
    if not raw:
        return current
    return raw in {"y", "yes", "1", "true", "on", "enable", "enabled"}


def _prompt_choice(label: str, current: str, choices: list[str]) -> str:
    value = (current or "").strip().lower()
    valid = {item.lower(): item for item in choices}
    if value not in valid:
        value = choices[0].lower()
    raw = input(f"{label} ({'/'.join(choices)}) [{value}]: ").strip().lower()
    if not raw:
        return value
    if raw in valid:
        return raw
    print(f"Invalid choice: {raw}. Keeping: {value}")
    return value


def _mask_identity(value: str) -> str:
    token = (value or "").strip()
    if not token:
        return "(not set)"
    if len(token) <= 5:
        return "*" * len(token)
    return token[:2] + ("*" * (len(token) - 4)) + token[-2:]


def _print_accounts_status(payload: dict[str, Any]) -> None:
    records = payload.get("accounts") if isinstance(payload.get("accounts"), dict) else {}
    print("Accounts setup")
    print(f"Supported: {', '.join(sorted(SUPPORTED_ACCOUNTS.keys()))}")
    if not records:
        print("Configured: none")
        print("Run: cv accounts linkedin")
        return

    print("Configured:")
    for name in sorted(records.keys()):
        row = records.get(name) if isinstance(records.get(name), dict) else {}
        enabled = bool(row.get("enabled", False))
        identity = _mask_identity(str(row.get("username", "")))
        mfa = str(row.get("mfa", "unknown"))
        updated = str(row.get("updated_at", ""))
        print(f"- {name}: enabled={'yes' if enabled else 'no'} user={identity} mfa={mfa} updated={updated}")


def _interactive_setup(name: str, current: dict[str, Any]) -> dict[str, Any]:
    print(f"Setting up account profile: {name}")
    print("Password storage is intentionally not supported. Use browser profile sessions instead.")

    updated = dict(current)
    updated["enabled"] = _prompt_bool("Enable this account for automation", bool(current.get("enabled", False)))
    updated["username"] = _prompt_text("Login email or username", str(current.get("username", "")))
    updated["profile_url"] = _prompt_text("Profile URL (optional)", str(current.get("profile_url", "")))
    updated["login_url"] = _prompt_text("Login URL", str(current.get("login_url", "")) or str(SUPPORTED_ACCOUNTS.get(name, {}).get("login_url", "")))
    updated["browser_profile_dir"] = _prompt_text(
        "Browser profile dir",
        str(current.get("browser_profile_dir", "")) or _default_browser_profile_dir(name),
        required=True,
    )
    updated["session_strategy"] = _prompt_choice(
        "Session strategy",
        str(current.get("session_strategy", "persistent-profile")),
        ["persistent-profile", "manual-each-run"],
    )
    updated["manual_login_required"] = _prompt_bool(
        "Manual login required before auto-apply",
        bool(current.get("manual_login_required", True)),
    )
    updated["mfa"] = _prompt_choice("MFA status", str(current.get("mfa", "unknown")), ["unknown", "enabled", "disabled"])
    updated["notes"] = _prompt_text("Notes (optional)", str(current.get("notes", "")))
    updated["updated_at"] = now_iso()
    return updated


def cmd_accounts(args: list[str]) -> int:
    root = require_project()
    payload = _load_accounts(root)

    if not args or args[0].strip().lower() in {"list", "status"}:
        _print_accounts_status(payload)
        return 0

    raw_name = args[0].strip().lower()
    normalized = raw_name.replace("_", "").replace("-", "")

    matched_name = ""
    for name in SUPPORTED_ACCOUNTS:
        if normalized == name.replace("-", ""):
            matched_name = name
            break

    if not matched_name:
        die(f"Unsupported account name: {raw_name}. Supported: {', '.join(sorted(SUPPORTED_ACCOUNTS.keys()))}")

    accounts = payload.get("accounts") if isinstance(payload.get("accounts"), dict) else {}
    current = accounts.get(matched_name) if isinstance(accounts.get(matched_name), dict) else _default_account_record(matched_name)
    current = {**_default_account_record(matched_name), **current}

    updated = _interactive_setup(matched_name, current)
    accounts[matched_name] = updated
    payload["accounts"] = accounts
    payload["version"] = 1

    config_path = _save_accounts(root, payload)
    print("Account profile saved.")
    print(f"Account: {matched_name}")
    print(f"Enabled: {'yes' if bool(updated.get('enabled', False)) else 'no'}")
    print(f"Session strategy: {updated.get('session_strategy', '')}")
    print(f"Config file: {config_path.relative_to(root)}")
    return 0
