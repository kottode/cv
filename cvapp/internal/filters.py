from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..config import CVState
from ..utils import now_iso, slugify


def filters_dir(root: Path) -> Path:
    path = root / "filters"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_filter_name(state: CVState) -> str:
    token = slugify(state.current_job or "default")
    return token or "default"


def filter_file(root: Path, name: str) -> Path:
    safe = slugify(name) or "default"
    return filters_dir(root) / f"{safe}.json"


def default_profile() -> dict[str, Any]:
    return {
        "name": "default",
        "seniority": [],
        "locations": [],
        "accept_remote": True,
        "phone": "",
        "email": "",
        "salary_min": 0,
        "job_types": [],
        "updated_at": now_iso(),
    }


def load_filter_profile(root: Path, name: str) -> dict[str, Any]:
    path = filter_file(root, name)
    profile = default_profile()
    profile["name"] = slugify(name) or "default"
    if not path.is_file():
        return profile

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return profile

    if not isinstance(parsed, dict):
        return profile

    profile["seniority"] = [str(v).strip().lower() for v in parsed.get("seniority", []) if str(v).strip()]
    profile["locations"] = [str(v).strip().lower() for v in parsed.get("locations", []) if str(v).strip()]
    profile["accept_remote"] = bool(parsed.get("accept_remote", True))
    profile["phone"] = str(parsed.get("phone", "")).strip()
    profile["email"] = str(parsed.get("email", "")).strip()
    try:
        profile["salary_min"] = max(0, int(parsed.get("salary_min", 0)))
    except Exception:
        profile["salary_min"] = 0
    profile["job_types"] = [str(v).strip().lower() for v in parsed.get("job_types", []) if str(v).strip()]
    profile["updated_at"] = str(parsed.get("updated_at", now_iso()))
    return profile


def save_filter_profile(root: Path, profile: dict[str, Any]) -> Path:
    name = slugify(str(profile.get("name", "default"))) or "default"
    path = filter_file(root, name)
    payload = {
        "name": name,
        "seniority": [str(v).strip().lower() for v in profile.get("seniority", []) if str(v).strip()],
        "locations": [str(v).strip().lower() for v in profile.get("locations", []) if str(v).strip()],
        "accept_remote": bool(profile.get("accept_remote", True)),
        "phone": str(profile.get("phone", "")).strip(),
        "email": str(profile.get("email", "")).strip(),
        "salary_min": max(0, int(profile.get("salary_min", 0) or 0)),
        "job_types": [str(v).strip().lower() for v in profile.get("job_types", []) if str(v).strip()],
        "updated_at": now_iso(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def list_filter_profiles(root: Path) -> list[str]:
    names: list[str] = []
    for child in sorted(filters_dir(root).glob("*.json")):
        names.append(child.stem)
    return names


def filter_signature(profile: dict[str, Any]) -> str:
    stable = {
        "seniority": profile.get("seniority", []),
        "locations": profile.get("locations", []),
        "accept_remote": bool(profile.get("accept_remote", True)),
        "phone": str(profile.get("phone", "")).strip(),
        "email": str(profile.get("email", "")).strip(),
        "salary_min": int(profile.get("salary_min", 0) or 0),
        "job_types": profile.get("job_types", []),
    }
    raw = json.dumps(stable, sort_keys=True, ensure_ascii=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _matches_any_token(text: str, tokens: list[str]) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in tokens)


def profile_filter_reason(profile: dict[str, Any], post: dict[str, Any], job_text: str) -> str:
    title = str(post.get("title", "")).lower()
    location = str(post.get("location", "")).lower()
    full_text = f"{title}\n{location}\n{job_text}".lower()

    phone = str(profile.get("phone", "")).strip()
    email = str(profile.get("email", "")).strip()
    if not phone:
        return "profile-missing-phone"
    if not email:
        return "profile-missing-email"

    seniority = [str(v).strip().lower() for v in profile.get("seniority", []) if str(v).strip()]
    if seniority and (not _matches_any_token(full_text, seniority)):
        return "profile-seniority-mismatch"

    locations = [str(v).strip().lower() for v in profile.get("locations", []) if str(v).strip()]
    accept_remote = bool(profile.get("accept_remote", True))
    has_remote = "remote" in full_text
    if locations:
        in_location = _matches_any_token(full_text, locations)
        if not in_location and not (accept_remote and has_remote):
            return "profile-location-mismatch"
    elif (not accept_remote) and has_remote:
        return "profile-remote-not-accepted"

    job_types = [str(v).strip().lower() for v in profile.get("job_types", []) if str(v).strip()]
    if job_types and (not _matches_any_token(full_text, job_types)):
        return "profile-job-type-mismatch"

    salary_min = int(profile.get("salary_min", 0) or 0)
    if salary_min > 0:
        salary_values: list[int] = []
        for raw in re.findall(r"\$\s*([0-9][0-9,]{2,})", full_text):
            token = raw.replace(",", "")
            try:
                salary_values.append(int(token))
            except Exception:
                continue
        if salary_values and max(salary_values) < salary_min:
            return "profile-salary-below-min"

    return ""
