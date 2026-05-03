#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

CV_VERSION = "0.2.0"
DEFAULT_MODEL = "gpt-5-mini"
STATE_DIR = Path(".cv")
STATE_FILE = STATE_DIR / "state.env"
LEGACY_TRACK_FILE = STATE_DIR / "track.tsv"
TRACK_FILE_NAME = "track.tsv"
POSTS_FILE_NAME = "posts.json"
AUTO_CONFIG_FILE = STATE_DIR / "auto.env"
TELEGRAM_CONFIG_FILE = Path.home() / ".config" / "cv" / "telegram.env"
TELEGRAM_SETUP_TEST_MESSAGE = "cv telegram integration connected"
TAG_STOPWORDS = {
    "and", "the", "for", "with", "from", "that", "this", "your", "you", "into", "over", "under", "about",
    "have", "has", "had", "are", "was", "were", "will", "would", "can", "could", "should", "our", "their",
    "its", "via", "using", "use", "used", "per", "plus", "year", "years", "month", "months", "present",
    "current", "work", "experience", "summary", "skills", "education", "languages", "add", "measurable", "impact",
    "team", "role", "company", "candidate", "professional", "title", "job", "responsibilities",
}

TECH_TAG_PATTERNS: list[tuple[str, str]] = [
    ("typescript", r"\btypescript\b"),
    ("javascript", r"\bjavascript\b"),
    ("react", r"\breact(?:\.js)?\b"),
    ("next.js", r"\bnext\.js\b|\bnextjs\b"),
    ("nestjs", r"\bnest\.js\b|\bnestjs\b"),
    ("node.js", r"\bnode(?:\.js)?\b"),
    ("vue", r"\bvue(?:\.js)?\b"),
    ("angular", r"\bangular\b"),
    ("svelte", r"\bsvelte\b"),
    ("redux", r"\bredux\b"),
    ("graphql", r"\bgraphql\b"),
    ("rest api", r"\brest(?:ful)?\b|\bapi\b"),
    ("docker", r"\bdocker\b"),
    ("kubernetes", r"\bkubernetes\b|\bk8s\b"),
    ("aws", r"\baws\b|\bamazon web services\b"),
    ("gcp", r"\bgcp\b|\bgoogle cloud\b"),
    ("azure", r"\bazure\b"),
    ("ci/cd", r"\bci/?cd\b|\bcontinuous integration\b|\bcontinuous delivery\b"),
    ("github actions", r"\bgithub actions\b"),
    ("gitlab ci", r"\bgitlab\b"),
    ("jenkins", r"\bjenkins\b"),
    ("terraform", r"\bterraform\b"),
    ("ansible", r"\bansible\b"),
    ("sql", r"\bsql\b"),
    ("postgresql", r"\bpostgres(?:ql)?\b"),
    ("mysql", r"\bmysql\b"),
    ("mongodb", r"\bmongodb\b"),
    ("redis", r"\bredis\b"),
    ("kafka", r"\bkafka\b"),
    ("rabbitmq", r"\brabbitmq\b"),
    ("grpc", r"\bgrpc\b"),
    ("microservices", r"\bmicroservice(?:s)?\b"),
    ("linux", r"\blinux\b"),
    ("bash", r"\bbash\b|\bshell scripting\b"),
    ("python", r"\bpython\b"),
    ("django", r"\bdjango\b"),
    ("flask", r"\bflask\b"),
    ("fastapi", r"\bfastapi\b"),
    ("java", r"\bjava\b"),
    ("spring", r"\bspring\b"),
    ("c#", r"\bc#\b|\bdotnet\b|\.net"),
    ("c++", r"\bc\+\+\b"),
    ("go", r"\bgolang\b|\bgo\b"),
    ("rust", r"\brust\b"),
    ("php", r"\bphp\b"),
    ("laravel", r"\blaravel\b"),
    ("html", r"\bhtml\b"),
    ("css", r"\bcss\b"),
    ("sass", r"\bsass\b|\bscss\b"),
    ("tailwind", r"\btailwind\b"),
    ("webpack", r"\bwebpack\b"),
    ("vite", r"\bvite\b"),
    ("jest", r"\bjest\b"),
    ("cypress", r"\bcypress\b"),
    ("playwright", r"\bplaywright\b"),
    ("testing library", r"\btesting library\b"),
    ("storybook", r"\bstorybook\b"),
    ("figma", r"\bfigma\b"),
    ("accessibility", r"\baccessibility\b|\bwcag\b|\ba11y\b"),
    ("performance", r"\bperformance\b|\bweb vitals\b"),
]

NOISY_TAG_TOKENS = {
    "yyyy", "mm", "here", "goes", "add", "candidate", "summary", "impact", "skill", "skills",
}

SHORT_TAG_ALLOWLIST = {"go", "ui", "ux", "qa", "ai", "ml", "bi", "aws", "gcp", "c#"}
COMPOSITE_KEEP_TAGS = {"ci/cd", "ui/ux", "r&d", "b2b", "b2c"}


class CVError(Exception):
    pass


@dataclass
class CVState:
    current_job: str = "default"
    current_name: str = "resume"
    current_title: str = "Professional Title"


@dataclass
class AutoConfig:
    enabled: bool = False
    search_urls: list[str] = field(default_factory=list)
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    min_score: int = 60
    max_posts: int = 12
    max_links_per_seed: int = 25
    auto_apply: bool = True
    notify: bool = True
    last_run_at: str = ""
    last_seeked: int = 0
    last_parsed: int = 0
    last_filtered: int = 0
    last_stored: int = 0
    last_applied: int = 0
    last_error: str = ""


def die(message: str) -> None:
    raise CVError(message)


def warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "default"


def pretty_name(value: str) -> str:
    words = value.replace("-", " ").split()
    return " ".join(word[:1].upper() + word[1:].lower() for word in words)


def normalize_tag(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[`*_#>\[\](){}]", " ", value)
    value = re.sub(r"[^a-z0-9+.#/& -]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .-_/&:")
    return value


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_iso(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def quote_env(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def unquote_env(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        inner = value[1:-1]
        return bytes(inner, "utf-8").decode("unicode_escape")
    return value


def find_project_root(start: Path) -> Path | None:
    start = start.resolve()
    for candidate in [start, *start.parents]:
        if (candidate / STATE_FILE).is_file():
            return candidate
    return None


def require_project() -> Path:
    root = find_project_root(Path.cwd())
    if root is None:
        die("No CV project found in current path. Run: cv init")
    os.chdir(root)
    return root


def load_state(root: Path) -> CVState:
    path = root / STATE_FILE
    if not path.is_file():
        die("State file missing. Run: cv init")

    state = CVState()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = unquote_env(value)
        if key == "CURRENT_JOB":
            state.current_job = value or "default"
        elif key == "CURRENT_NAME":
            state.current_name = value or "resume"
        elif key == "CURRENT_TITLE":
            state.current_title = value or "Professional Title"
    return state


def save_state(root: Path, state: CVState) -> None:
    path = root / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            f"CURRENT_JOB={quote_env(state.current_job)}",
            f"CURRENT_NAME={quote_env(state.current_name)}",
            f"CURRENT_TITLE={quote_env(state.current_title)}",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def current_resume_path(state: CVState) -> Path:
    return Path("jobs") / state.current_job / f"{state.current_name}.md"


def current_track_path(state: CVState) -> Path:
    return Path("jobs") / state.current_job / TRACK_FILE_NAME


def current_posts_path(state: CVState) -> Path:
    return Path("jobs") / state.current_job / POSTS_FILE_NAME


def write_resume_template(resume_name: str, title: str) -> str:
    display_name = pretty_name(resume_name)
    return (
        f"# {display_name}\n"
        f"**{title}**\n\n"
        "## Summary\n"
        "- Candidate summary goes here.\n\n"
        "## Work Experience\n"
        "### Company | Title | YYYY-MM to YYYY-MM\n"
        "- Add measurable impact.\n\n"
        "## Skills\n"
        "- Skill 1\n"
        "- Skill 2\n\n"
        "## Education\n"
        "- Degree, School, Year\n\n"
        "## Languages\n"
        "- English (Fluent)\n"
    )


def ensure_resume_exists(root: Path, state: CVState) -> Path:
    resume = root / current_resume_path(state)
    if not resume.is_file():
        resume.parent.mkdir(parents=True, exist_ok=True)
        resume.write_text(write_resume_template(state.current_name, state.current_title), encoding="utf-8")
    return resume


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def normalize_section_name(value: str) -> str:
    lower = value.lower()
    mapping = {
        "summary": "Summary",
        "skills": "Skills",
        "skill": "Skills",
        "education": "Education",
        "edu": "Education",
        "languages": "Languages",
        "language": "Languages",
        "lang": "Languages",
        "work-experience": "Work Experience",
        "work_experience": "Work Experience",
        "workexperience": "Work Experience",
        "experience": "Work Experience",
        "exp": "Work Experience",
    }
    return mapping.get(lower, value)


def extract_section_body(text: str, section: str) -> str:
    pattern = re.compile(rf"^## {re.escape(section)}\s*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1).rstrip("\n")


def replace_section_body(text: str, section: str, body: str) -> str:
    body = body.strip("\n")
    block = f"## {section}\n"
    if body:
        block += body + "\n"

    pattern = re.compile(rf"^## {re.escape(section)}\s*\n.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    if pattern.search(text):
        updated = pattern.sub(block, text, count=1)
    else:
        tail = "" if text.endswith("\n") else "\n"
        sep = "\n" if text.strip() else ""
        updated = f"{text}{tail}{sep}{block}"

    # Normalize trailing newline
    if not updated.endswith("\n"):
        updated += "\n"
    return updated


def section_exists(text: str, section: str) -> bool:
    return re.search(rf"^## {re.escape(section)}$", text, flags=re.MULTILINE) is not None


def ensure_track_file(root: Path, state: CVState) -> Path:
    path = root / current_track_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)

    legacy = root / LEGACY_TRACK_FILE
    if not path.is_file() and legacy.is_file() and state.current_job == "default":
        shutil.copy2(legacy, path)

    if not path.is_file():
        path.write_text("item\tstatus\tupdated_at\tapplied_at\n", encoding="utf-8")
    return path


def ensure_posts_file(root: Path, state: CVState) -> Path:
    path = root / current_posts_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        payload = {
            "version": 1,
            "updated_at": now_iso(),
            "posts": [],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def load_posts(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        posts = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("posts"), list):
        posts = parsed.get("posts")
    else:
        posts = []

    valid_posts: list[dict[str, Any]] = []
    for item in posts:
        if isinstance(item, dict):
            valid_posts.append(item)
    return valid_posts


def save_posts(path: Path, posts: list[dict[str, Any]]) -> None:
    ordered = sorted(posts, key=lambda row: str(row.get("updated_at", "")), reverse=True)
    payload = {
        "version": 1,
        "updated_at": now_iso(),
        "posts": ordered,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def read_track_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if idx == 0:
            continue
        if not line.strip():
            continue
        parts = line.split("\t")
        while len(parts) < 4:
            parts.append("")
        item, status, updated_at, applied_at = parts[:4]
        rows.append(
            {
                "item": item,
                "status": status,
                "updated_at": updated_at,
                "applied_at": applied_at,
            }
        )
    return rows


def write_track_rows(path: Path, rows: list[dict[str, str]]) -> None:
    lines = ["item\tstatus\tupdated_at\tapplied_at"]
    for row in rows:
        lines.append(
            "\t".join(
                [
                    row.get("item", ""),
                    row.get("status", ""),
                    row.get("updated_at", ""),
                    row.get("applied_at", ""),
                ]
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def maybe_mark_ghosted(path: Path) -> list[dict[str, str]]:
    rows = read_track_rows(path)
    now = dt.datetime.now(dt.timezone.utc)
    changed = False

    for row in rows:
        status = row.get("status", "")
        if status != "applied" and not status.startswith("interview"):
            continue
        applied_dt = parse_iso(row.get("applied_at", ""))
        if applied_dt is None:
            continue
        days = (now - applied_dt).days
        if days >= 30:
            row["status"] = "ghosted"
            row["updated_at"] = now_iso()
            changed = True

    if changed:
        write_track_rows(path, rows)
    return rows


def upsert_track_item(path: Path, item: str, status: str) -> dict[str, str]:
    rows = maybe_mark_ghosted(path)
    now = now_iso()

    for row in rows:
        if row.get("item") != item:
            continue
        if not row.get("applied_at") or status == "applied":
            row["applied_at"] = now
        row["status"] = status
        row["updated_at"] = now
        write_track_rows(path, rows)
        return row

    row = {
        "item": item,
        "status": status,
        "updated_at": now,
        "applied_at": now,
    }
    rows.append(row)
    write_track_rows(path, rows)
    return row


def status_token_to_full(token: str) -> str:
    token = token.lower()
    if token in {"", "applied", "a"}:
        return "applied"
    if token in {"interview", "i", "int"}:
        return "interview1"
    match = re.fullmatch(r"(?:i|int)(\d+)", token)
    if match:
        return f"interview{match.group(1)}"
    if token in {"rejected", "r"}:
        return "rejected"
    if token in {"offer", "o"}:
        return "offer"
    if token in {"ghosted", "g"}:
        return "ghosted"
    if token == "status":
        return "status"
    die(f"Unknown status token: {token}")
    return ""  # unreachable


def is_status_token(token: str) -> bool:
    token = token.lower()
    if token in {"applied", "a", "interview", "i", "int", "rejected", "r", "offer", "o", "ghosted", "g", "status"}:
        return True
    return re.fullmatch(r"(?:i|int)\d+", token) is not None


def remove_prompt_hook() -> None:
    helper_file = Path.home() / ".local" / "share" / "cv" / "prompt.sh"
    bashrc = Path.home() / ".bashrc"
    marker_start = "# >>> cv prompt >>>"
    marker_end = "# <<< cv prompt <<<"

    try:
        helper_file.unlink(missing_ok=True)
    except Exception:
        pass

    if not bashrc.exists():
        return

    content = bashrc.read_text(encoding="utf-8")
    block_pattern = re.compile(
        rf"\n?{re.escape(marker_start)}\n.*?{re.escape(marker_end)}\n?",
        flags=re.DOTALL,
    )
    cleaned = block_pattern.sub("\n", content)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    bashrc.write_text(cleaned, encoding="utf-8")


def run_copilot(prompt: str, capture: bool = False) -> str:
    if shutil.which("copilot") is None:
        die("copilot CLI not found")

    args = ["copilot", "--model", DEFAULT_MODEL, "--allow-all-paths", "-p", prompt, "-s"]
    if capture:
        proc = subprocess.run(args, text=True, capture_output=True)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, args, output=proc.stdout, stderr=proc.stderr)
        return proc.stdout

    proc = subprocess.run(args)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args)
    return ""


def load_env_style_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = unquote_env(value.strip())
    return values


def parse_env_bool(value: str, default: bool = False) -> bool:
    token = (value or "").strip().lower()
    if token in {"1", "true", "yes", "on", "enabled", "enable"}:
        return True
    if token in {"0", "false", "no", "off", "disabled", "disable"}:
        return False
    return default


def parse_env_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def parse_env_list(value: str) -> list[str]:
    raw = str(value or "")
    parts = [chunk.strip() for chunk in re.split(r"[\n,;|]", raw) if chunk.strip()]
    seen: set[str] = set()
    values: list[str] = []
    for item in parts:
        if item in seen:
            continue
        seen.add(item)
        values.append(item)
    return values


def auto_config_file(root: Path) -> Path:
    return root / AUTO_CONFIG_FILE


def load_auto_config(root: Path) -> AutoConfig:
    path = auto_config_file(root)
    values = load_env_style_file(path)

    env_search = parse_env_list(os.environ.get("CV_AUTO_SEARCH_URLS", ""))
    config = AutoConfig(
        enabled=parse_env_bool(values.get("AUTO_ENABLED", "0"), default=False),
        search_urls=parse_env_list(values.get("AUTO_SEARCH_URLS", "")) or env_search,
        include_keywords=parse_env_list(values.get("AUTO_INCLUDE_KEYWORDS", "")),
        exclude_keywords=parse_env_list(values.get("AUTO_EXCLUDE_KEYWORDS", "")),
        min_score=parse_env_int(values.get("AUTO_MIN_SCORE", "60"), default=60, minimum=0, maximum=100),
        max_posts=parse_env_int(values.get("AUTO_MAX_POSTS", "12"), default=12, minimum=1, maximum=200),
        max_links_per_seed=parse_env_int(values.get("AUTO_MAX_LINKS_PER_SEED", "25"), default=25, minimum=1, maximum=200),
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
    return config


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


def save_telegram_config(bot_token: str, chat_id: str) -> Path:
    TELEGRAM_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            f"TELEGRAM_BOT_TOKEN={quote_env(bot_token.strip())}",
            f"TELEGRAM_CHAT_ID={quote_env(chat_id.strip())}",
            "",
        ]
    )
    TELEGRAM_CONFIG_FILE.write_text(content, encoding="utf-8")
    try:
        os.chmod(TELEGRAM_CONFIG_FILE, 0o600)
    except Exception:
        pass
    return TELEGRAM_CONFIG_FILE


def load_telegram_config() -> dict[str, str]:
    values = load_env_style_file(TELEGRAM_CONFIG_FILE)
    token = (values.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (values.get("TELEGRAM_CHAT_ID") or "").strip()
    return {"bot_token": token, "chat_id": chat_id}


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + ("*" * (len(value) - 8)) + value[-4:]


def send_telegram_message(bot_token: str, chat_id: str, message: str) -> tuple[bool, str]:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return False, str(exc)

    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        parsed = {}

    if isinstance(parsed, dict) and parsed.get("ok") is True:
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else {}
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if message_id is None:
            return True, "ok"
        return True, f"message_id={message_id}"

    if isinstance(parsed, dict) and parsed.get("description"):
        return False, str(parsed.get("description"))
    return False, response_text[:500]


def fetch_telegram_updates(bot_token: str, offset: int | None = None, timeout_seconds: int = 10) -> tuple[bool, dict[str, Any], str]:
    params: dict[str, str] = {"timeout": str(timeout_seconds)}
    if offset is not None:
        params["offset"] = str(offset)

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds + 5) as response:
            response_text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return False, {}, str(exc)

    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        return False, {}, "Invalid JSON response from Telegram"

    if not isinstance(parsed, dict):
        return False, {}, "Unexpected response from Telegram"
    if parsed.get("ok") is not True:
        return False, parsed, str(parsed.get("description") or "Telegram API error")
    return True, parsed, ""


def extract_start_chat_id(payload: dict[str, Any]) -> tuple[str | None, int | None]:
    updates = payload.get("result") if isinstance(payload.get("result"), list) else []
    best_offset: int | None = None

    for item in updates:
        if not isinstance(item, dict):
            continue

        update_id = item.get("update_id")
        if isinstance(update_id, int):
            candidate_offset = update_id + 1
            if best_offset is None or candidate_offset > best_offset:
                best_offset = candidate_offset

        message = item.get("message") if isinstance(item.get("message"), dict) else None
        if message is None:
            continue

        text = str(message.get("text") or "").strip().lower()
        if not text.startswith("/start"):
            continue

        chat = message.get("chat") if isinstance(message.get("chat"), dict) else None
        if chat is None:
            continue

        chat_id = chat.get("id")
        if chat_id is None:
            continue
        return str(chat_id), best_offset

    return None, best_offset


def discover_telegram_chat_id(bot_token: str) -> tuple[bool, str, str]:
    print("Send /start to your bot now.")
    print("Waiting up to ~60 seconds for update...")

    ok, initial_payload, error = fetch_telegram_updates(bot_token, offset=None, timeout_seconds=2)
    if not ok:
        return False, "", error

    _, offset = extract_start_chat_id(initial_payload)

    for _attempt in range(8):
        ok, payload, error = fetch_telegram_updates(bot_token, offset=offset, timeout_seconds=8)
        if not ok:
            return False, "", error

        chat_id, next_offset = extract_start_chat_id(payload)
        if next_offset is not None:
            offset = next_offset
        if chat_id:
            return True, chat_id, ""

    return False, "", "Could not find /start update in time. Send /start and retry."


def cmd_ci_telegram(args: list[str]) -> int:
    action = args[0].strip().lower() if args else "setup"

    if action in {"setup", "config", "configure"}:
        token = os.environ.get("CV_TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            token = input("Telegram bot token: ").strip()
        if not token:
            die("Telegram bot token required")

        chat_id = os.environ.get("CV_TELEGRAM_CHAT_ID", "").strip()
        if not chat_id:
            ok, discovered_chat_id, discover_error = discover_telegram_chat_id(token)
            if not ok:
                die(f"Telegram chat id auto-discovery failed: {discover_error}")
            chat_id = discovered_chat_id
        if not chat_id:
            die("Telegram chat id required")

        ok, detail = send_telegram_message(token, chat_id, TELEGRAM_SETUP_TEST_MESSAGE)
        if not ok:
            die(f"Telegram /start auto-reply failed: {detail}")

        config_path = save_telegram_config(token, chat_id)
        print("Telegram integration configured.")
        print(f"Detected chat id: {chat_id}")
        print(f"Auto-reply message: {TELEGRAM_SETUP_TEST_MESSAGE}")
        print(f"Reply result: {detail}")
        print(f"Config file: {config_path}")
        return 0

    if action == "status":
        config = load_telegram_config()
        token = config.get("bot_token", "")
        chat_id = config.get("chat_id", "")
        if not token or not chat_id:
            print("Telegram integration: not configured")
            print("Run: cv ci telegram")
            return 0

        print("Telegram integration: configured")
        print(f"Bot token: {mask_secret(token)}")
        print(f"Chat id: {chat_id}")
        print(f"Config file: {TELEGRAM_CONFIG_FILE}")
        return 0

    if action == "send":
        config = load_telegram_config()
        token = config.get("bot_token", "")
        chat_id = config.get("chat_id", "")
        if not token or not chat_id:
            die("Telegram integration not configured. Run: cv ci telegram")

        if len(args) > 1:
            message = " ".join(args[1:]).strip()
        else:
            message = sys.stdin.read().strip()

        if not message:
            die("Usage: cv ci telegram send <message> or pipe message via stdin")

        if len(message) > 4000:
            message = message[:4000]

        ok, detail = send_telegram_message(token, chat_id, message)
        if not ok:
            die(f"Telegram send failed: {detail}")

        print("Telegram message sent.")
        print(f"Result: {detail}")
        return 0

    die("Usage: cv ci telegram [setup|status|send] [message]")
    return 1


def cmd_ci(args: list[str]) -> int:
    if not args:
        die("Usage: cv ci telegram [setup|status|send] [message]")

    provider = args[0].strip().lower()
    if provider == "telegram":
        return cmd_ci_telegram(args[1:])

    die("Usage: cv ci telegram [setup|status|send] [message]")
    return 1


def editor_command() -> str:
    return os.environ.get("EDITOR", "vi")


def cmd_help() -> int:
    print(
        textwrap.dedent(
            """\
            cv - resume workflow CLI

            Usage:
                cv init [name]
                cv install [target]
                cv current
                cv jobs [job] [name]
                cv title <new title>
                cv section [list|show|set|add|edit] ...
                cv skills [list|add|rm|manage] ...
                cv exp [list|add|rm|manage] ...
                cv tags [text|url]
                cv say <question>
                cv fit <text|url>
                cv tailor [text|url]
                cv track [item] [status]
                cv posts [list|all|filtered|show <index>]
                cv auto [status|enable|disable]
                cv ats [senior]
                cv ci telegram [setup|status|send] [message]
                cv help

            Examples:
                cv init john-bang-gang
                cv jobs frontend
                cv title Frontend Developer
                cv skills add \"React\"
                cv exp add \"Acme|Frontend Engineer|2022-01|Present\"
                cv fit \"Senior Frontend role with React TypeScript\"
                cv fit https://example.com/jobs/frontend-engineer
                cv tailor https://example.com/jobs/frontend-engineer
                cv tailor \"Senior frontend role with React TypeScript\"
                cv tags
                cv tags https://example.com/jobs/frontend-engineer
                cv posts
                cv auto status
                cv auto enable
                cv ats senior
                cv ci telegram
                cv ci telegram send \"Build finished\"
            """
        )
    )
    return 0


def cmd_install(args: list[str]) -> int:
    target = Path(args[0]).expanduser() if args else (Path.home() / ".local" / "bin" / "cv")
    script_dir = Path(__file__).resolve().parent
    source_cv = script_dir / "cv"
    source_core = script_dir / "cv_core.py"

    if not source_cv.is_file():
        die(f"cv script not found at {source_cv}")
    if not source_core.is_file():
        die(f"cv_core.py not found at {source_core}")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_cv, target)
    shutil.copy2(source_core, target.parent / "cv_core.py")
    os.chmod(target, 0o755)

    print(f"Installed: {target}")
    print(f"Ensure PATH contains: {target.parent}")
    return 0


def cmd_init(args: list[str]) -> int:
    root = Path.cwd()

    resume_name = args[0] if args else ""
    if not resume_name:
        proc = subprocess.run(["git", "config", "--get", "user.name"], text=True, capture_output=True)
        if proc.returncode == 0:
            resume_name = proc.stdout.strip()
    if not resume_name:
        resume_name = "resume"

    resume_name = slugify(resume_name)

    (root / STATE_DIR).mkdir(parents=True, exist_ok=True)
    (root / "jobs" / "default").mkdir(parents=True, exist_ok=True)
    (root / "tailored").mkdir(parents=True, exist_ok=True)

    state = CVState(current_job="default", current_name=resume_name, current_title="Professional Title")
    save_state(root, state)
    ensure_resume_exists(root, state)
    ensure_track_file(root, state)
    remove_prompt_hook()

    print("Initialized CV project.")
    print(f"Current resume: {current_resume_path(state)}")
    print("Prompt hook disabled. Existing cv prompt hook removed from ~/.bashrc if present.")
    return 0


def cmd_current(args: list[str]) -> int:
    del args
    root = require_project()
    state = load_state(root)
    ensure_resume_exists(root, state)

    print(f"Job: {state.current_job}")
    print(f"Name: {state.current_name}")
    print(f"File: {current_resume_path(state)}")
    return 0


def cmd_jobs(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    ensure_resume_exists(root, state)

    if not args or args[0] == "list":
        jobs_dir = root / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        print("Available jobs:")
        found = False
        for child in sorted(jobs_dir.iterdir()):
            if child.is_dir():
                found = True
                marker = "*" if child.name == state.current_job else " "
                print(f" {marker} {child.name}")
        if not found:
            print(" (none)")
        return 0

    if args[0] == "current":
        return cmd_current([])

    new_job = slugify(args[0])
    new_name = slugify(args[1]) if len(args) > 1 else state.current_name

    state.current_job = new_job
    state.current_name = new_name
    save_state(root, state)

    resume = ensure_resume_exists(root, state)
    ensure_track_file(root, state)
    print(f"Switched to: {resume.relative_to(root)}")
    return 0


def cmd_title(args: list[str]) -> int:
    if not args:
        die("Usage: cv title <new title>")

    root = require_project()
    state = load_state(root)
    resume = ensure_resume_exists(root, state)

    new_title = " ".join(args).strip()
    text = read_text(resume)

    if re.search(r"^\*\*.*\*\*$", text, flags=re.MULTILINE):
        text = re.sub(r"^\*\*.*\*\*$", f"**{new_title}**", text, flags=re.MULTILINE, count=1)
    else:
        lines = text.splitlines()
        if lines:
            lines.insert(1, f"**{new_title}**")
            lines.insert(2, "")
        else:
            lines = [f"**{new_title}**", ""]
        text = "\n".join(lines)
        if not text.endswith("\n"):
            text += "\n"

    write_text(resume, text)
    state.current_title = new_title
    save_state(root, state)
    print(f"Updated title in {resume.relative_to(root)}")
    return 0


def cmd_section(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    resume = ensure_resume_exists(root, state)
    text = read_text(resume)

    action = args[0] if args else "list"

    if action == "list":
        print(f"Sections in {resume.relative_to(root)}:")
        for section in ["Summary", "Work Experience", "Skills", "Education", "Languages"]:
            status = "present" if section_exists(text, section) else "missing"
            print(f" - {section} [{status}]")
        return 0

    if action == "show":
        if len(args) < 2:
            die("Usage: cv section show <section>")
        section = normalize_section_name(args[1])
        print(extract_section_body(text, section))
        return 0

    if action == "set":
        if len(args) < 3:
            die("Usage: cv section set <section> <content>")
        section = normalize_section_name(args[1])
        body = " ".join(args[2:])
        updated = replace_section_body(text, section, body)
        write_text(resume, updated)
        print(f"Updated section: {section}")
        return 0

    if action == "add":
        if len(args) < 2:
            die("Usage: cv section add <section>")
        section = normalize_section_name(args[1])
        if section_exists(text, section):
            print(f"Section already exists: {section}")
            return 0
        updated = replace_section_body(text, section, "")
        write_text(resume, updated)
        print(f"Added section: {section}")
        return 0

    if action in {"edit", "manage"}:
        if len(args) < 2:
            die("Usage: cv section edit <section>")
        section = normalize_section_name(args[1])
        print(f"Section {section} content:")
        print(extract_section_body(text, section))
        print("Open full file in editor for detailed edits.")
        subprocess.call([editor_command(), str(resume)])
        return 0

    die(f"Unknown section action: {action}")
    return 1


def cmd_skills(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    resume = ensure_resume_exists(root, state)
    text = read_text(resume)

    action = args[0] if args else "list"

    if action == "list":
        body = extract_section_body(text, "Skills")
        if not body.strip():
            print("No skills section content.")
            return 0
        skills = [line[2:].strip() for line in body.splitlines() if line.strip().startswith("- ")]
        for idx, skill in enumerate(skills, start=1):
            print(f"{idx:2d}. {skill}")
        return 0

    if action == "add":
        skill = " ".join(args[1:]).strip()
        if not skill:
            die("Usage: cv skills add <skill>")
        body = extract_section_body(text, "Skills")
        lines = [line.rstrip() for line in body.splitlines() if line.strip()]
        target = f"- {skill}"
        if target in lines:
            print("Skill already exists.")
            return 0
        lines.append(target)
        updated = replace_section_body(text, "Skills", "\n".join(lines))
        write_text(resume, updated)
        print(f"Added skill: {skill}")
        return 0

    if action in {"rm", "remove", "del", "delete"}:
        skill = " ".join(args[1:]).strip()
        if not skill:
            die("Usage: cv skills rm <skill>")
        body = extract_section_body(text, "Skills")
        lines = [line for line in body.splitlines() if line.strip() and line.strip() != f"- {skill}"]
        updated = replace_section_body(text, "Skills", "\n".join(lines))
        write_text(resume, updated)
        print(f"Removed skill: {skill}")
        return 0

    if action in {"manage", "edit"}:
        subprocess.call([editor_command(), str(resume)])
        return 0

    die(f"Unknown skills action: {action}")
    return 1


def month_index(value: str) -> int | None:
    raw = value.strip().replace("/", "-")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", raw):
        return None
    year, month = raw.split("-")
    month_i = int(month)
    if month_i < 1 or month_i > 12:
        return None
    return int(year) * 12 + month_i


def parse_date_range(value: str) -> tuple[str, str, int, int] | None:
    cleaned = value.strip()
    cleaned = re.sub(r"(?i)^date\s*:\s*", "", cleaned)
    cleaned = cleaned.replace("/", "-")
    cleaned = re.sub(r"\s+", " ", cleaned)

    match = re.search(
        r"([0-9]{4}-[0-9]{2})\s*(?:to|\-|–|—|until)\s*([0-9]{4}-[0-9]{2}|present|current)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        return parse_named_month_date_range(cleaned)

    start_raw, end_raw = match.group(1), match.group(2)
    start_m = month_index(start_raw)
    if start_m is None:
        return None

    end_label = end_raw.strip()
    if end_label.lower() in {"present", "current"}:
        now = dt.datetime.now()
        end_m = now.year * 12 + now.month
        end_out = "Present"
    else:
        end_m = month_index(end_label)
        if end_m is None:
            return None
        end_out = end_label

    if end_m < start_m:
        return None

    return start_raw, end_out, start_m, end_m


def parse_named_month_date_range(value: str) -> tuple[str, str, int, int] | None:
    month_map = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "sept": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }

    def month_from_name(name: str) -> int | None:
        key = name.strip().lower()[:4]
        return month_map.get(key[:3]) or month_map.get(key)

    cleaned = re.sub(r"\s+", " ", value.strip())
    match = re.search(
        r"([A-Za-z]{3,9})\s+([0-9]{4})\s*(?:to|\-|–|—|until)\s*(?:(?:([A-Za-z]{3,9})\s+([0-9]{4}))|(present|current))",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    start_month_name, start_year, end_month_name, end_year, end_present = match.groups()
    start_month = month_from_name(start_month_name)
    if start_month is None:
        return None
    start_raw = f"{start_year}-{start_month:02d}"
    start_m = int(start_year) * 12 + start_month

    if end_present:
        now = dt.datetime.now()
        end_m = now.year * 12 + now.month
        end_out = "Present"
    else:
        if not end_month_name or not end_year:
            return None
        end_month = month_from_name(end_month_name)
        if end_month is None:
            return None
        end_out = f"{end_year}-{end_month:02d}"
        end_m = int(end_year) * 12 + end_month

    if end_m < start_m:
        return None

    return start_raw, end_out, start_m, end_m


def clean_heading_value(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^\*\*(.*?)\*\*$", r"\1", value)
    value = re.sub(r"\s+", " ", value).strip(" -|")
    return value


def parse_experience_entries(body: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    blocks = re.split(r"(?=^###\s+)", body, flags=re.MULTILINE)

    for block in blocks:
        block = block.strip()
        if not block.startswith("###"):
            continue

        lines = [line.rstrip() for line in block.splitlines()]
        lines = [line for line in lines if line.strip()]
        if not lines:
            continue

        heading = re.sub(r"^###\s*", "", lines[0]).strip()
        heading = clean_heading_value(heading)

        def parse_title_line(raw_value: str) -> tuple[str | None, str | None]:
            stripped = raw_value.strip()
            if not stripped:
                return None, None
            if stripped.startswith("- ") or stripped.startswith("* "):
                return None, None

            payload = stripped
            label_match = re.match(r"(?i)^(position|role|title)\s*:\s*(.+)$", payload)
            if label_match:
                payload = label_match.group(2).strip()

            bold_with_date = re.match(r"^\*\*(.*?)\*\*\s*(?:\(([^()]{6,})\))?$", payload)
            if bold_with_date:
                return clean_heading_value(bold_with_date.group(1)), bold_with_date.group(2)

            plain_with_date = re.match(r"^([^()]{2,120})\s*\(([^()]{6,})\)\s*$", payload)
            if plain_with_date:
                return clean_heading_value(plain_with_date.group(1)), plain_with_date.group(2)

            if parse_date_range(payload) is not None:
                return None, None

            if 2 <= len(payload) <= 120:
                return clean_heading_value(payload), None

            return None, None

        def push_entry(
            company_name: str,
            title_value: str,
            start_value: str,
            end_value: str,
            start_month: int | None,
            end_month: int | None,
            desc_lines: list[str],
        ) -> None:
            if not company_name or not title_value:
                return
            entries.append(
                {
                    "company": company_name,
                    "title": clean_heading_value(title_value),
                    "start": start_value,
                    "end": end_value,
                    "start_m": start_month,
                    "end_m": end_month,
                    "description": "\n".join(desc_lines).strip(),
                }
            )

        company = ""
        current_title = ""
        current_start = ""
        current_end = ""
        current_start_m: int | None = None
        current_end_m: int | None = None
        current_desc: list[str] = []

        inline_three = re.match(r"^(.*?)\s*\|\s*(.*?)\s*\|\s*(.+)$", heading, flags=re.IGNORECASE)
        if inline_three:
            company = clean_heading_value(inline_three.group(1))
            current_title = clean_heading_value(inline_three.group(2))
            parsed = parse_date_range(inline_three.group(3))
            if parsed is not None:
                current_start, current_end, current_start_m, current_end_m = parsed
        else:
            inline_pair = re.match(r"^(.*?)\s*\|\s*(.+)$", heading, flags=re.IGNORECASE)
            if inline_pair:
                company = clean_heading_value(inline_pair.group(1))
                seed_title, seed_date = parse_title_line(inline_pair.group(2))
                if seed_title:
                    current_title = seed_title
                if seed_date:
                    parsed = parse_date_range(seed_date)
                    if parsed is not None:
                        current_start, current_end, current_start_m, current_end_m = parsed
            else:
                company = heading

        for raw in lines[1:]:
            stripped = raw.strip()
            if not stripped:
                continue

            parsed_title, parsed_title_date = parse_title_line(stripped)
            if parsed_title:
                if current_title:
                    push_entry(company, current_title, current_start, current_end, current_start_m, current_end_m, current_desc)
                    current_desc = []
                    current_start = ""
                    current_end = ""
                    current_start_m = None
                    current_end_m = None

                current_title = parsed_title
                if parsed_title_date:
                    parsed = parse_date_range(parsed_title_date)
                    if parsed is not None:
                        current_start, current_end, current_start_m, current_end_m = parsed
                continue

            if current_title and current_start_m is None:
                parsed = parse_date_range(stripped)
                if parsed is not None:
                    current_start, current_end, current_start_m, current_end_m = parsed
                    continue

            if current_title:
                current_desc.append(stripped)

        if current_title:
            push_entry(company, current_title, current_start, current_end, current_start_m, current_end_m, current_desc)

    return entries


def merge_unique_tags(primary: list[str], extra: list[str], limit: int = 35) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in [*primary, *extra]:
        normalized = normalize_tag(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
        if len(merged) >= limit:
            break
    return merged


def ats_enrichment_text(parsed: dict[str, Any]) -> str:
    if not parsed:
        return ""

    parts: list[str] = []
    designation = parsed.get("designation")
    if isinstance(designation, str) and designation.strip():
        parts.append(designation.strip())

    skills = parsed.get("skills")
    if isinstance(skills, list):
        parts.extend(str(item).strip() for item in skills if str(item).strip())

    company_names = parsed.get("company_names")
    if isinstance(company_names, list):
        parts.extend(str(item).strip() for item in company_names if str(item).strip())

    return "\n".join(parts)


def ats_fields_subset(parsed: dict[str, Any]) -> dict[str, Any]:
    if not parsed:
        return {}
    return {
        "name": parsed.get("name"),
        "email": parsed.get("email"),
        "mobile_number": parsed.get("mobile_number"),
        "skills": parsed.get("skills"),
        "total_experience": parsed.get("total_experience"),
        "degree": parsed.get("degree"),
        "designation": parsed.get("designation"),
        "company_names": parsed.get("company_names"),
    }


def cmd_exp(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    resume = ensure_resume_exists(root, state)
    text = read_text(resume)
    action = args[0] if args else "list"

    if action == "list":
        title_match = re.search(r"^\*\*(.*?)\*\*$", text, flags=re.MULTILINE)
        target_title = title_match.group(1).strip().lower() if title_match else state.current_title.lower()
        body = extract_section_body(text, "Work Experience")
        entries = parse_experience_entries(body)
        provider, parsed, hint = run_external_ats_parser(text, auto_setup=False)

        if hint:
            warn(hint)

        if not entries:
            print("No parseable entries. Expected format:")
            print("### Company")
            print("Title or **Title**")
            print("YYYY-MM to YYYY-MM")
            return 0

        def words(value: str) -> set[str]:
            return set(re.findall(r"[a-z0-9]+", value.lower()))

        target_words = {w for w in words(target_title) if len(w) > 1}

        entries.sort(key=lambda row: row.get("start_m") if isinstance(row.get("start_m"), int) else -1, reverse=True)
        print("#  Company | Title | Range | Relevance")
        for idx, row in enumerate(entries, start=1):
            title_words = {w for w in words(row["title"]) if len(w) > 1}
            overlap = (len(target_words & title_words) / len(target_words)) if target_words else 0.0
            if row.get("start") and row.get("end"):
                range_label = f"{row['start']} to {row['end']}"
            else:
                range_label = "unknown"
            print(f"{idx}. {row['company']} | {row['title']} | {range_label} | {round(overlap * 100)}%")

        dated_entries = [
            row
            for row in entries
            if isinstance(row.get("start_m"), int) and isinstance(row.get("end_m"), int)
        ]

        if dated_entries:
            intervals = sorted((int(row["start_m"]), int(row["end_m"])) for row in dated_entries)
            merged: list[list[int]] = []
            for start_m, end_m in intervals:
                if not merged or start_m > merged[-1][1]:
                    merged.append([start_m, end_m])
                else:
                    merged[-1][1] = max(merged[-1][1], end_m)

            total_months = sum(end - start for start, end in merged)
            total_years = total_months / 12 if total_months > 0 else 0

            ordered = sorted(dated_entries, key=lambda row: int(row["start_m"]))
            gap_months = 0
            prev_end = int(ordered[0]["end_m"])
            for row in ordered[1:]:
                row_start = int(row["start_m"])
                row_end = int(row["end_m"])
                if row_start > prev_end:
                    gap_months += row_start - prev_end
                prev_end = max(prev_end, row_end)

            print(f"Total experience years: {total_years:.1f}")
            print(f"Total gap months: {gap_months}")
        else:
            print("Total experience years: n/a (missing date ranges)")
            print("Total gap months: n/a (missing date ranges)")

        if parsed:
            companies = parsed.get("company_names") if isinstance(parsed.get("company_names"), list) else []
            print(f"ATS validation source: {provider}")
            if companies:
                preview = ", ".join(str(item) for item in companies[:8])
                print(f"ATS company hints: {preview}")
        return 0

    if action == "add":
        payload = " ".join(args[1:]).strip()
        if not payload:
            die('Usage: cv exp add "Company|Title|YYYY-MM|YYYY-MM or Present"')
        parts = [part.strip() for part in payload.split("|")]
        if len(parts) != 4:
            die('Usage: cv exp add "Company|Title|YYYY-MM|YYYY-MM or Present"')
        company, role, start, end = parts

        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", start):
            die("Start date must be YYYY-MM")
        if not re.fullmatch(r"(?:[0-9]{4}-[0-9]{2}|Present|Current)", end):
            die("End date must be YYYY-MM, Present, or Current")

        body = extract_section_body(text, "Work Experience")
        entry = f"### {company} | {role} | {start} to {end}\n- Add measurable impact."
        new_body = f"{body.strip()}\n\n{entry}".strip()
        updated = replace_section_body(text, "Work Experience", new_body)
        write_text(resume, updated)
        print("Added experience entry.")
        return 0

    if action in {"rm", "remove", "del", "delete"}:
        if len(args) < 2 or not args[1].isdigit():
            die("Usage: cv exp rm <index>")
        idx = int(args[1])
        body = extract_section_body(text, "Work Experience")
        blocks = re.split(r"(?=^### )", body, flags=re.MULTILINE)
        entries = [block for block in blocks if block.strip().startswith("### ")]
        if idx < 1 or idx > len(entries):
            die(f"Index out of range. Current entries: {len(entries)}")
        remove_block = entries[idx - 1]
        new_body = body.replace(remove_block, "", 1)
        new_body = re.sub(r"\n{3,}", "\n\n", new_body).strip("\n")
        updated = replace_section_body(text, "Work Experience", new_body)
        write_text(resume, updated)
        print(f"Removed experience entry {idx}.")
        return 0

    if action in {"manage", "edit"}:
        subprocess.call([editor_command(), str(resume)])
        return 0

    die(f"Unknown exp action: {action}")
    return 1


def extract_frequency_keywords(text: str, top_n: int = 80) -> list[str]:
    words = [w.strip(".-") for w in re.findall(r"[a-z0-9+.#/&-]+", text.lower())]
    words = [w for w in words if len(w) >= 3 and w not in TAG_STOPWORDS and w not in NOISY_TAG_TOKENS]

    unigram_counts = Counter(words)
    bigram_counts: Counter[str] = Counter()

    for idx in range(len(words) - 1):
        bigram = f"{words[idx]} {words[idx + 1]}"
        if words[idx] not in TAG_STOPWORDS and words[idx + 1] not in TAG_STOPWORDS:
            bigram_counts[bigram] += 1

    merged: list[str] = []
    merged.extend([phrase for phrase, count in bigram_counts.most_common(top_n) if count >= 2])
    merged.extend([phrase for phrase, count in unigram_counts.most_common(top_n) if count >= 2])
    return merged[: top_n * 3]


def extract_meaningful_tags(text: str, max_tags: int = 80) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    company_blacklist: set[str] = set()

    def split_compound_terms(value: str) -> list[str]:
        normalized = normalize_tag(value)
        if not normalized:
            return []
        if re.search(r"\bci\s*/\s*cd\b", normalized):
            return ["ci/cd"]
        if re.search(r"\bui\s*/\s*ux\b", normalized):
            return ["ui/ux"]
        if normalized in COMPOSITE_KEEP_TAGS:
            return [normalized]
        if "/" in normalized or "&" in normalized or " and " in normalized:
            chunks = [chunk.strip() for chunk in re.split(r"\s*(?:/|&|\band\b)\s*", normalized) if chunk.strip()]
            if len(chunks) > 1:
                return chunks
        return [normalized]

    def maybe_strip_skill_prefix(value: str) -> str:
        value = value.strip()
        value = re.sub(r"^\*\*[^*]{1,40}:\*\*\s*", "", value)
        value = re.sub(r"^[A-Za-z0-9+.#/& -]{2,30}:\s*", "", value)
        return value.strip()

    def add_tag(value: str) -> None:
        tag = normalize_tag(value)
        if not tag or tag in seen:
            return
        if len(tag) > 80:
            return
        if len(tag) < 3 and tag not in SHORT_TAG_ALLOWLIST:
            return
        tokens = [token for token in re.split(r"[\s/-]+", tag) if token]
        if not tokens:
            return
        if len(tokens) > 4:
            return
        if tag in company_blacklist:
            return
        if tag in TAG_STOPWORDS:
            return
        if all(token in TAG_STOPWORDS for token in tokens):
            return
        if any(token in NOISY_TAG_TOKENS for token in tokens):
            return
        if tokens[0] in TAG_STOPWORDS or tokens[-1] in TAG_STOPWORDS:
            return
        if any(token in {"and", "or", "with", "using", "did"} for token in tokens):
            return
        if re.fullmatch(r"[0-9./-]+", tag):
            return
        if re.search(r"\b[0-9]{4}-[0-9]{2}\b", tag):
            return
        seen.add(tag)
        tags.append(tag)

    if not text.strip():
        return tags

    title_match = re.search(r"^\*\*(.*?)\*\*$", text, flags=re.MULTILINE)
    if title_match:
        add_tag(title_match.group(1))

    work_body = extract_section_body(text, "Work Experience")
    for heading in re.findall(r"^###\s*(.+?)\s*$", work_body, flags=re.MULTILINE):
        heading = heading.strip()
        if not heading:
            continue
        if "|" in heading:
            parts = [normalize_tag(part) for part in heading.split("|") if normalize_tag(part)]
            if parts:
                company_blacklist.add(parts[0])
            if len(parts) > 1:
                add_tag(parts[1])
        else:
            company_blacklist.add(normalize_tag(heading))

    for role in re.findall(r"^\*\*(.*?)\*\*", work_body, flags=re.MULTILINE):
        role = re.sub(r"\s*\(.*?\)\s*$", "", role).strip()
        if role:
            add_tag(role)

    skills_body = extract_section_body(text, "Skills")
    for line in skills_body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        item = maybe_strip_skill_prefix(stripped[2:].strip())
        if not item:
            continue
        for part in re.split(r"[,;|]", item):
            part = part.strip()
            if not part:
                continue
            for chunk in split_compound_terms(part):
                add_tag(chunk)

    # Include package names and explicit tool mentions from dedicated sections.
    open_source_body = extract_section_body(text, "Open Source Packages")
    for pkg in re.findall(r"^\s*-\s*\*\*(.*?)\*\*", open_source_body, flags=re.MULTILINE):
        add_tag(pkg)

    lowered = text.lower()
    for name, pattern in TECH_TAG_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            add_tag(name)

    try:
        import yake  # type: ignore

        focus_blocks = [
            extract_section_body(text, "Summary"),
            extract_section_body(text, "Skills"),
            extract_section_body(text, "Work Experience"),
            extract_section_body(text, "AI & LLM"),
            extract_section_body(text, "Open Source Packages"),
        ]
        focus_text = "\n".join(block for block in focus_blocks if block.strip())
        if not focus_text.strip():
            focus_text = text

        extractor = yake.KeywordExtractor(lan="en", n=3, top=max_tags * 4, dedupLim=0.85)
        for phrase, _score in extractor.extract_keywords(focus_text):
            cleaned = normalize_tag(phrase)
            if not cleaned:
                continue
            if len(cleaned.split()) > 3:
                continue
            add_tag(cleaned)
            for token in cleaned.split():
                if len(token) >= 3 and token not in TAG_STOPWORDS:
                    add_tag(token)
            if len(tags) >= max_tags:
                break
    except Exception:
        pass

    if len(tags) < max_tags:
        for phrase in extract_frequency_keywords(text, top_n=max_tags):
            add_tag(phrase)
            if len(tags) >= max_tags:
                break

    return tags[:max_tags]


def build_tags_from_resume(text: str) -> list[str]:
    return extract_meaningful_tags(text, max_tags=35)


def resolve_job_text_argument(raw_input: str) -> tuple[str, str, str]:
    source_value = raw_input.strip()
    if re.match(r"^https?://", source_value, flags=re.IGNORECASE):
        return "url", source_value, extract_primary_text_from_url(source_value)
    return "text", source_value, source_value


def cmd_tags(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    resume = ensure_resume_exists(root, state)
    text = read_text(resume)

    resume_tags = build_tags_from_resume(text)
    provider, parsed, hint = run_external_ats_parser(text, auto_setup=False)
    if hint:
        warn(hint)

    ats_seed = ats_enrichment_text(parsed)
    if ats_seed:
        ats_tags = extract_meaningful_tags(ats_seed, max_tags=35)
        resume_tags = merge_unique_tags(resume_tags, ats_tags, limit=35)
    resume_count = len(resume_tags)
    fits = 25 <= resume_count <= 35

    print(f"Resume tags count: {resume_count}")
    print(f"ATS enrichment source: {provider}")
    print(f"Fits 25-35 range: {'yes' if fits else 'no'}")
    if resume_count < 25:
        print(f"Need at least +{25 - resume_count} more tags.")
    elif resume_count > 35:
        print(f"Need to trim at least {resume_count - 35} tags.")

    if resume_tags:
        print("\nResume tags:")
        for idx, tag in enumerate(resume_tags, start=1):
            print(f"{idx}. {tag}")

    if args:
        source_kind, source_value, job_text = resolve_job_text_argument(" ".join(args))
        job_text = re.sub(r"\s+", " ", job_text).strip()
        if not job_text:
            die("Job description is empty")

        job_tags = extract_meaningful_tags(job_text, max_tags=50)
        resume_set = set(resume_tags)
        overlap = [tag for tag in job_tags if tag in resume_set]
        missing = [tag for tag in job_tags if tag not in resume_set]
        coverage = int(round((len(overlap) / len(job_tags)) * 100)) if job_tags else 0

        print("\nJob tag analysis")
        print(f"Source: {source_kind}")
        if source_kind == "url":
            print(f"URL: {source_value}")
        print(f"Job tags count: {len(job_tags)}")
        print(f"Resume coverage of job tags: {coverage}%")
        print("Matched tags: " + (", ".join(overlap[:30]) if overlap else "none"))
        print("Missing tags: " + (", ".join(missing[:30]) if missing else "none"))

    return 0


class PrimaryTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_stack: list[bool] = []
        self.in_main = 0
        self.main_parts: list[str] = []
        self.parts: list[str] = []

    def _active_skip(self) -> bool:
        return bool(self.skip_stack and self.skip_stack[-1])

    @staticmethod
    def _is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
        attrs_map = {k.lower(): (v or "") for k, v in attrs}
        if "hidden" in attrs_map:
            return True
        style = attrs_map.get("style", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            return True
        if attrs_map.get("aria-hidden", "").lower() == "true":
            return True
        if attrs_map.get("type", "").lower() == "hidden":
            return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        skip_tags = {
            "script", "style", "noscript", "header", "footer", "nav", "aside", "form",
            "input", "button", "select", "option", "textarea", "svg", "canvas", "iframe",
            "img", "picture", "video", "audio",
        }
        block_tags = {
            "main", "article", "section", "div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr",
        }

        tag = tag.lower()
        parent_skip = self._active_skip()
        this_skip = parent_skip or tag in skip_tags or self._is_hidden(attrs)
        self.skip_stack.append(this_skip)

        if this_skip:
            return

        if tag == "main":
            self.in_main += 1

        if tag in block_tags:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        block_tags = {
            "main", "article", "section", "div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr",
        }

        tag = tag.lower()
        if not self.skip_stack:
            return
        this_skip = self.skip_stack.pop()

        if not this_skip and tag == "main" and self.in_main > 0:
            self.in_main -= 1

        if not this_skip and tag in block_tags:
            self._append("\n")

    def handle_data(self, data: str) -> None:
        if self._active_skip():
            return
        text = re.sub(r"\s+", " ", data).strip()
        if text:
            self._append(text)

    def _append(self, value: str) -> None:
        if self.in_main > 0:
            self.main_parts.append(value)
        self.parts.append(value)


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def extract_jsonld_text(html: str) -> str:
    chunks: list[str] = []
    pattern = re.compile(r"<script[^>]*type=[\"']application/ld\\+json[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)

    def collect(obj: Any) -> None:
        if isinstance(obj, dict):
            for key in ["title", "description", "responsibilities", "qualifications"]:
                value = obj.get(key)
                if isinstance(value, str):
                    cleaned = strip_tags(value)
                    if len(cleaned) > 30:
                        chunks.append(cleaned)
            for value in obj.values():
                collect(value)
        elif isinstance(obj, list):
            for item in obj:
                collect(item)

    for match in pattern.finditer(html):
        payload = match.group(1).strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        collect(data)

    return "\n".join(dict.fromkeys(chunks))


def extract_script_embedded_text(html: str) -> str:
    chunks: list[str] = []
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)

    patterns = [
        r'"jobDescription"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"description"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"responsibilities"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"qualifications"\s*:\s*"((?:\\.|[^"\\])*)"',
    ]

    for script in scripts:
        lowered = script.lower()
        if "description" not in lowered and "job" not in lowered:
            continue
        for pattern in patterns:
            for raw in re.findall(pattern, script, flags=re.IGNORECASE | re.DOTALL):
                try:
                    decoded = bytes(raw, "utf-8").decode("unicode_escape")
                except UnicodeDecodeError:
                    decoded = raw
                cleaned = strip_tags(decoded)
                if len(cleaned) > 60:
                    chunks.append(cleaned)

    return "\n".join(dict.fromkeys(chunks))


def extract_primary_text_from_url(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
    except Exception as exc:  # pragma: no cover
        die(f"URL fetch error: {exc}")

    charset_match = re.search(r"charset=([A-Za-z0-9_-]+)", content_type)
    encoding = charset_match.group(1) if charset_match else "utf-8"
    html = raw.decode(encoding, errors="replace")

    if "html" not in content_type.lower() and "<html" not in html[:2000].lower():
        plain = re.sub(r"\s+", " ", html).strip()
        return plain[:20000]

    candidates: list[str] = []

    jsonld = extract_jsonld_text(html)
    if jsonld.strip():
        candidates.append(jsonld)

    embedded = extract_script_embedded_text(html)
    if embedded.strip():
        candidates.append(embedded)

    parser = PrimaryTextParser()
    parser.feed(html)

    main_text = "\n".join(parser.main_parts)
    all_text = "\n".join(parser.parts)
    chosen = main_text if len(main_text) >= 300 else all_text
    chosen = re.sub(r"\n{3,}", "\n\n", chosen)
    chosen_lines = [re.sub(r"\s+", " ", line).strip() for line in chosen.splitlines()]
    chosen_lines = [line for line in chosen_lines if len(line) >= 20]
    chosen_text = "\n".join(chosen_lines).strip()
    if chosen_text:
        candidates.append(chosen_text)

    plain = strip_tags(html)
    if plain:
        candidates.append(plain)

    # Prefer richest candidate and cap length
    best = ""
    for candidate in candidates:
        candidate = candidate.strip()
        if len(candidate) > len(best):
            best = candidate

    return best[:20000]


def keywords_from_text(text: str, top_n: int = 40) -> list[str]:
    return extract_meaningful_tags(text, max_tags=top_n)


def normalize_url_for_store(url: str) -> str:
    raw = url.strip()
    if not raw:
        return ""

    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        return raw

    filtered_pairs: list[tuple[str, str]] = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False):
        key_l = key.lower()
        if key_l.startswith("utm_") or key_l in {"gclid", "fbclid", "trk", "tracking", "source"}:
            continue
        filtered_pairs.append((key, value))

    clean_path = parsed.path or "/"
    if clean_path != "/":
        clean_path = clean_path.rstrip("/") or "/"

    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            clean_path,
            "",
            urllib.parse.urlencode(filtered_pairs),
            "",
        )
    )


def looks_like_job_url(url: str) -> bool:
    lowered = url.lower()
    markers = [
        "job", "jobs", "career", "careers", "position", "positions", "opening", "openings", "opportunity",
        "greenhouse", "lever", "workday", "ashby", "smartrecruiters", "icims", "recruit",
    ]
    return any(marker in lowered for marker in markers)


def fetch_url_html(url: str) -> tuple[bool, str, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read()
    except Exception as exc:
        return False, "", "", str(exc)

    charset_match = re.search(r"charset=([A-Za-z0-9_-]+)", content_type)
    encoding = charset_match.group(1) if charset_match else "utf-8"
    html = raw.decode(encoding, errors="replace")
    return True, html, content_type, ""


def extract_links_from_html(base_url: str, html: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE):
        href = raw.strip()
        if not href or href.startswith("#"):
            continue
        if href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue

        absolute = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme.lower() not in {"http", "https"}:
            continue

        normalized = normalize_url_for_store(absolute)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)
    return links


def discover_job_urls(seed_url: str, max_links: int) -> list[str]:
    normalized_seed = normalize_url_for_store(seed_url)
    if not normalized_seed:
        return []

    urls: list[str] = []
    if looks_like_job_url(normalized_seed):
        urls.append(normalized_seed)

    ok, html, content_type, error = fetch_url_html(normalized_seed)
    if not ok:
        warn(f"auto: seed fetch failed for {normalized_seed}: {error}")
        return urls or [normalized_seed]

    html_like = "html" in content_type.lower() or "<html" in html[:2000].lower()
    if not html_like:
        return urls or [normalized_seed]

    candidates = extract_links_from_html(normalized_seed, html)
    for candidate in candidates:
        if looks_like_job_url(candidate):
            urls.append(candidate)

    if not urls:
        urls.append(normalized_seed)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in urls:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
        if len(deduped) >= max_links:
            break
    return deduped


def fit_grade(score: int) -> str:
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def analyze_job_fit(job_text: str, resume_keywords: set[str]) -> dict[str, Any]:
    job_tags = list(dict.fromkeys(keywords_from_text(job_text, top_n=60)))
    common = [tag for tag in job_tags if tag in resume_keywords]
    missing = [tag for tag in job_tags if tag not in resume_keywords]
    score = int(round((len(common) / len(job_tags)) * 100)) if job_tags else 0
    return {
        "job_tags": job_tags,
        "matched_tags": common,
        "missing_tags": missing,
        "score": score,
        "grade": fit_grade(score),
    }


def keyword_filter_reason(job_text: str, include_keywords: list[str], exclude_keywords: list[str]) -> str:
    lowered = job_text.lower()

    include = [item.lower().strip() for item in include_keywords if item.strip()]
    exclude = [item.lower().strip() for item in exclude_keywords if item.strip()]

    if include and not any(token in lowered for token in include):
        return "missing include keywords"

    for token in exclude:
        if token in lowered:
            return f"matched exclude keyword: {token}"

    return ""


def infer_company_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    path_parts = [part for part in parsed.path.split("/") if part]

    raw = ""
    if host.endswith("lever.co") and path_parts:
        raw = path_parts[0]
    elif host.endswith("greenhouse.io") and path_parts:
        raw = path_parts[0]
    elif host.endswith("ashbyhq.com") and path_parts:
        raw = path_parts[0]
    elif host.endswith("myworkdayjobs.com") and path_parts:
        raw = path_parts[0]
    else:
        raw = host.split(".")[0] if host else "company"

    return pretty_name(slugify(raw))


def infer_title_from_text_and_url(job_text: str, url: str) -> str:
    blocked_terms = re.compile(
        r"(job description|responsibilities|requirements|about us|benefits|equal opportunity|apply now)",
        flags=re.IGNORECASE,
    )
    title_terms = re.compile(
        r"\b(engineer|developer|manager|designer|scientist|architect|lead|principal|intern|analyst|consultant)\b",
        flags=re.IGNORECASE,
    )

    compact = re.sub(r"\s+", " ", job_text).strip()
    inline_match = re.search(
        r"\b((?:senior|staff|lead|principal|junior|sr\.?|jr\.?)?\s*[A-Za-z0-9+/#& -]{0,50}(?:engineer|developer|manager|designer|scientist|architect|analyst|consultant|intern))\b",
        compact,
        flags=re.IGNORECASE,
    )
    if inline_match:
        candidate = re.sub(r"\s+", " ", inline_match.group(1)).strip(" -|:")
        if 6 <= len(candidate) <= 90 and not blocked_terms.search(candidate):
            return candidate

    lines = [line.strip(" -|:\t") for line in job_text.splitlines() if line.strip()]
    for line in lines[:120]:
        if len(line) < 6 or len(line) > 120:
            continue
        if blocked_terms.search(line):
            continue
        if title_terms.search(line):
            return line

    for line in lines[:40]:
        if 6 <= len(line) <= 100 and not blocked_terms.search(line):
            return line

    parsed = urllib.parse.urlparse(url)
    path_parts = [slugify(part) for part in parsed.path.split("/") if slugify(part)]
    if path_parts:
        fallback = path_parts[-1]
        if fallback in {"jobs", "job", "careers", "positions", "apply", "view"} and len(path_parts) >= 2:
            fallback = path_parts[-2]
        return pretty_name(fallback)
    return "Role"


def build_post_item_label(company: str, title: str) -> str:
    left = company.strip() or "Company"
    right = title.strip() or "Role"
    return f"{left} | {right}"[:140]


def upsert_post_record(posts: list[dict[str, Any]], record: dict[str, Any]) -> bool:
    target_url = normalize_url_for_store(str(record.get("url", "")))
    for row in posts:
        row_url = normalize_url_for_store(str(row.get("url", "")))
        if row_url != target_url:
            continue

        first_seen = row.get("first_seen_at") or row.get("discovered_at") or now_iso()
        existing_apply_status = str(row.get("apply_status", "")).strip()
        existing_applied_at = str(row.get("applied_at", "")).strip()
        existing_track_item = str(row.get("track_item", "")).strip()

        row.update(record)
        row["first_seen_at"] = first_seen
        if existing_apply_status == "applied" and row.get("apply_status") != "applied":
            row["apply_status"] = existing_apply_status
        if existing_applied_at and not row.get("applied_at"):
            row["applied_at"] = existing_applied_at
        if existing_track_item and not row.get("track_item"):
            row["track_item"] = existing_track_item
        return False

    posts.append(record)
    return True


def attempt_playwright_auto_apply(url: str) -> tuple[str, str]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # type: ignore
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        return "manual-required", f"playwright unavailable: {exc}"

    selectors = [
        "button:has-text('Easy Apply')",
        "a:has-text('Easy Apply')",
        "button:has-text('Apply Now')",
        "a:has-text('Apply Now')",
        "button:has-text('Apply')",
        "a:has-text('Apply')",
        "button[type='submit']",
    ]

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(500)

            clicked = False
            click_note = ""

            for selector in selectors:
                locator = page.locator(selector)
                try:
                    count = locator.count()
                except Exception:
                    count = 0
                if count <= 0:
                    continue
                locator.first.click(timeout=7000)
                clicked = True
                click_note = f"clicked selector: {selector}"
                break

            if not clicked:
                href = page.evaluate(
                    """() => {
                        const targets = Array.from(document.querySelectorAll('a[href], button'));
                        for (const el of targets) {
                            const text = (el.textContent || '').toLowerCase();
                            if (text.includes('apply')) {
                                if (el.tagName.toLowerCase() === 'a') {
                                    return el.getAttribute('href') || '';
                                }
                                try { el.click(); return '__BUTTON_CLICKED__'; } catch (_) {}
                            }
                        }
                        return '';
                    }"""
                )

                if isinstance(href, str) and href:
                    if href == "__BUTTON_CLICKED__":
                        clicked = True
                        click_note = "clicked generic apply button"
                    else:
                        target = urllib.parse.urljoin(url, href)
                        page.goto(target, wait_until="domcontentloaded", timeout=45000)
                        clicked = True
                        click_note = f"navigated to apply link: {target}"

            browser.close()

        if clicked:
            return "applied", click_note or "apply interaction completed"
        return "manual-required", "could not find apply control"
    except PlaywrightTimeoutError as exc:
        return "failed", f"playwright timeout: {exc}"
    except Exception as exc:
        return "failed", f"playwright error: {exc}"


def send_auto_telegram_notification(message: str) -> tuple[bool, str]:
    config = load_telegram_config()
    token = (config.get("bot_token") or "").strip()
    chat_id = (config.get("chat_id") or "").strip()
    if not token or not chat_id:
        return False, "telegram not configured"
    return send_telegram_message(token, chat_id, message[:4000])


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
        for url in discover_job_urls(seed, config.max_links_per_seed):
            normalized = normalize_url_for_store(url)
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
            job_text = extract_primary_text_from_url(url)
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
            apply_status, apply_detail = attempt_playwright_auto_apply(url)
            if apply_status == "applied":
                applied_at = now_iso()
                track_item = build_post_item_label(company, title)
                upsert_track_item(track_path, track_item, "applied")
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


def cmd_fit(args: list[str]) -> int:
    if not args:
        die("Usage: cv fit <text|url>")

    root = require_project()
    state = load_state(root)
    resume = ensure_resume_exists(root, state)

    user_input = " ".join(args).strip()
    source_kind, source_value, job_text = resolve_job_text_argument(user_input)

    job_text = re.sub(r"\s+", " ", job_text).strip()
    if not job_text:
        die("Job description is empty")
    if len(job_text) > 12000:
        job_text = job_text[:12000]

    resume_text = read_text(resume)
    provider, parsed, hint = run_external_ats_parser(resume_text, auto_setup=False)
    if hint:
        warn(hint)
    ats_seed = ats_enrichment_text(parsed)

    resume_kw = set(keywords_from_text(resume_text, top_n=60))
    if ats_seed:
        resume_kw.update(keywords_from_text(ats_seed, top_n=30))
    job_kw = set(keywords_from_text(job_text, top_n=60))

    if not job_kw:
        score = 0
        common: list[str] = []
        missing: list[str] = []
    else:
        common = sorted(resume_kw & job_kw)
        missing = sorted(job_kw - resume_kw)
        score = int(round((len(common) / len(job_kw)) * 100))

    print(f"Source: {source_kind}")
    if source_kind == "url":
        print(f"URL: {source_value}")
    print(f"ATS enrichment source: {provider}")
    print(f"Job text chars used: {len(job_text)}")
    print("Non-AI fit precheck")
    print(f"Keyword overlap score: {score}/100")
    print("Common keywords: " + (", ".join(common[:25]) if common else "none"))
    print("Missing keywords: " + (", ".join(missing[:25]) if missing else "none"))

    if shutil.which("copilot"):
        prompt = (
            "You are a hiring manager and ATS reviewer.\n"
            "Assess fit between resume and job description.\n\n"
            f"Resume markdown:\n{resume_text}\n\n"
            f"Job description:\n{job_text}\n\n"
            "Return format:\n"
            "1) Fit score 0-100 with 1 sentence verdict.\n"
            "2) Top strengths (max 6 bullets).\n"
            "3) Gaps and risks (max 6 bullets).\n"
            "4) Missing high-impact keywords (comma-separated).\n"
            "5) Suggested rewrite for Summary section only.\n"
            "Be concise and concrete."
        )
        print("\nAI fit review")
        try:
            run_copilot(prompt)
        except subprocess.CalledProcessError:
            warn("AI fit review failed. Non-AI precheck still valid.")
    else:
        warn("copilot CLI not found. Skipped AI fit review.")
    return 0


def cmd_say(args: list[str]) -> int:
    if not args:
        die("Usage: cv say <question>")

    root = require_project()
    state = load_state(root)
    ensure_resume_exists(root, state)

    question = " ".join(args).strip()
    prompt = (
        "Context: Use markdown files in this directory, jobs folder, and tailored folder. "
        "Focus on candidate facts and resume tone. "
        f"Message: {question}"
    )
    run_copilot(prompt)
    return 0


def cmd_tailor(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    base = ensure_resume_exists(root, state)

    description = ""
    source_kind = ""
    source_value = ""
    if args:
        source_kind, source_value, description = resolve_job_text_argument(" ".join(args).strip())
        if not description:
            die("Job description is empty")

    company = ""
    role = ""

    if source_kind == "url":
        print(f"Loaded job description from URL: {source_value}")
        parsed = urllib.parse.urlparse(source_value)
        host = parsed.netloc.lower().split("@")[-1].split(":")[0]
        host = host[4:] if host.startswith("www.") else host
        host_slug = slugify(host) or "url-source"

        path_parts = [slugify(part) for part in parsed.path.split("/") if slugify(part)]
        job_ref = path_parts[-1] if path_parts else "job"

        company = "from-url"
        role = f"{host_slug}-{job_ref}".strip("-")
    else:
        company = input("Company: ").strip()
        if not company:
            die("Company required")

        role = input("Job title: ").strip()
        if not role:
            die("Job title required")

    if source_kind:
        description = re.sub(r"\s+", " ", description).strip()
        if not description:
            die("Job description is empty")
        if len(description) > 12000:
            description = description[:12000]
        if source_kind == "text":
            print("Loaded job description from text argument.")
    else:
        print("Paste job description. End input with Ctrl-D.")
        description = sys.stdin.read().strip()
        if not description:
            die("Job description required")

    company_slug = slugify(company) or "company"
    role_slug = slugify(role) or "role"
    company_slug = company_slug[:48].rstrip("-") or "company"
    role_slug = role_slug[:80].rstrip("-") or "role"

    out_dir = root / "tailored" / company_slug / role_slug
    out_dir.mkdir(parents=True, exist_ok=True)

    out_md = out_dir / f"{state.current_name}.md"
    out_docx = out_dir / f"{state.current_name}.docx"

    base_text = read_text(base)
    provider, parsed, hint = run_external_ats_parser(base_text, auto_setup=False)
    if hint:
        warn(hint)
    ats_fields = ats_fields_subset(parsed)

    if shutil.which("copilot"):
        metadata_header = ""
        source_rule = ""
        if source_kind == "url":
            metadata_header = f"Source URL: {source_value}\n"
            source_rule = (
                "- Infer company name and job title from the provided source description text.\n"
                "- Use the job title exactly as written in the source description; do not rewrite, normalize, or paraphrase it.\n"
            )
        else:
            metadata_header = f"Company: {company}\nTitle: {role}\n"

        prompt = (
            f"Context: Base resume file at {base.relative_to(root)}\n"
            f"External ATS source: {provider}\n"
            f"External ATS parsed fields JSON: {json.dumps(ats_fields)}\n"
            "Task: Tailor resume for role.\n"
            f"{metadata_header}"
            f"Description:\n{description}\n\n"
            "Rules:\n"
            "- Keep claims factual based on base resume only.\n"
            "- Keep markdown format.\n"
            "- Keep sections Summary, Work Experience, Skills, Education, Languages.\n"
            "- Improve ATS keyword alignment.\n"
            "- Keep concise action-oriented bullet points.\n"
            "- Use external ATS parsed fields as validation hints; do not invent facts.\n"
            f"{source_rule}"
            "Output only markdown."
        )
        try:
            tailored = run_copilot(prompt, capture=True)
            out_md.write_text(tailored, encoding="utf-8")
        except subprocess.CalledProcessError:
            warn("copilot run failed. Copying base resume instead.")
            shutil.copy2(base, out_md)
    else:
        warn("copilot CLI not found. Copying base resume instead.")
        shutil.copy2(base, out_md)

    if shutil.which("pandoc"):
        subprocess.run(["pandoc", str(out_md), "-o", str(out_docx)], check=False)
        print(f"Generated: {out_md.relative_to(root)}")
        print(f"Generated: {out_docx.relative_to(root)}")
    else:
        warn("pandoc not found. Skipped docx generation.")
        print(f"Generated: {out_md.relative_to(root)}")

    return 0


def cmd_track(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    path = ensure_track_file(root, state)

    if not args:
        rows = maybe_mark_ghosted(path)
        print(f"{'ITEM':30} {'STATUS':12} {'UPDATED':25} {'APPLIED':25}")
        print(f"{'-' * 30} {'-' * 12} {'-' * 25} {'-' * 25}")
        for row in rows:
            print(f"{row['item'][:30]:30} {row['status'][:12]:12} {row['updated_at'][:25]:25} {row['applied_at'][:25]:25}")
        return 0

    status = ""
    status_token = ""

    if len(args) >= 2 and is_status_token(args[-1]):
        status_token = args[-1]
        status = status_token_to_full(status_token)

    rows = maybe_mark_ghosted(path)

    if status == "status":
        item = " ".join(args[:-1]).strip()
        if not item:
            die("Usage: cv track <item> status")
        for row in rows:
            if row["item"] == item:
                print(f"Item: {row['item']}")
                print(f"Status: {row['status']}")
                print(f"Updated: {row['updated_at']}")
                print(f"Applied: {row['applied_at']}")
                return 0
        die(f"Track item not found: {item}")

    if status:
        item = " ".join(args[:-1]).strip()
    else:
        item = " ".join(args).strip()
        status = "applied"

    if not item:
        die("Track item cannot be empty")

    upsert_track_item(path, item, status)
    print(f"Tracked \"{item}\" as {status}")
    return 0


def cmd_posts(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    path = ensure_posts_file(root, state)
    posts = load_posts(path)
    posts = sorted(posts, key=lambda row: str(row.get("updated_at", "")), reverse=True)

    if not posts:
        print("No parsed posts yet.")
        print("Run: cv auto enable")
        return 0

    if args and args[0].lower() == "show":
        if len(args) < 2 or not args[1].isdigit():
            die("Usage: cv posts show <index>")
        idx = int(args[1])
        if idx < 1 or idx > len(posts):
            die(f"Index out of range. Available: 1..{len(posts)}")

        row = posts[idx - 1]
        print(f"Index: {idx}")
        print(f"URL: {row.get('url', '')}")
        print(f"Company: {row.get('company', '')}")
        print(f"Title: {row.get('title', '')}")
        print(f"Status: {row.get('status', '')}")
        print(f"Fit: {row.get('fit_score', 0)}/100 ({row.get('grade', 'D')})")
        print(f"Apply status: {row.get('apply_status', '')}")
        print(f"Apply detail: {row.get('apply_detail', '')}")
        print(f"Tracked item: {row.get('track_item', '')}")
        print(f"Updated: {row.get('updated_at', '')}")
        print("Matched tags: " + ", ".join(row.get("matched_tags", [])[:25]))
        print("Missing tags: " + ", ".join(row.get("missing_tags", [])[:25]))
        snippet = str(row.get("summary_snippet", ""))
        if snippet:
            print("Snippet:")
            print(snippet)
        return 0

    mode = args[0].lower() if args else "accepted"
    if mode in {"list", "accepted"}:
        rows = [row for row in posts if str(row.get("status", "")) == "accepted"]
    elif mode == "filtered":
        rows = [row for row in posts if str(row.get("status", "")) == "filtered"]
    elif mode == "all":
        rows = posts
    else:
        die("Usage: cv posts [list|all|filtered|show <index>]")

    print(f"Posts file: {path.relative_to(root)}")
    print(f"Showing {len(rows)} of {len(posts)} posts")
    print(f"{'#':>3} {'GRADE':5} {'FIT':5} {'STATUS':10} {'APPLY':14} {'COMPANY':16} {'TITLE':32}")
    print(f"{'-' * 3} {'-' * 5} {'-' * 5} {'-' * 10} {'-' * 14} {'-' * 16} {'-' * 32}")

    for idx, row in enumerate(rows, start=1):
        grade = str(row.get("grade", "D"))[:5]
        score = int(row.get("fit_score", 0)) if str(row.get("fit_score", "")).isdigit() else row.get("fit_score", 0)
        status = str(row.get("status", ""))[:10]
        apply_status = str(row.get("apply_status", ""))[:14]
        company = str(row.get("company", ""))[:16]
        title = str(row.get("title", ""))[:32]
        print(f"{idx:>3} {grade:5} {str(score)[:5]:5} {status:10} {apply_status:14} {company:16} {title:32}")

    print("Use: cv posts show <index> for full details")
    return 0


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
            ok, detail = send_auto_telegram_notification(summary_message)
            if ok:
                print("Telegram notification sent.")
            else:
                warn(f"Telegram notification skipped: {detail}")
        return 0

    die("Usage: cv auto [status|enable|disable]")
    return 1


def _run_setup_command(command: list[str]) -> tuple[bool, str]:
    env = os.environ.copy()
    env.setdefault("PIP_BREAK_SYSTEM_PACKAGES", "1")
    proc = subprocess.run(command, text=True, capture_output=True, env=env)
    output = (proc.stdout + "\n" + proc.stderr).strip()
    return proc.returncode == 0, output


def load_pyresparser_with_autosetup() -> tuple[Any | None, str | None]:
    manual_hint = (
        "python -m pip install --user pyresparser spacy nltk\n"
        "python -m pip install --user --break-system-packages pyresparser spacy nltk\n"
        "python -m spacy download en_core_web_sm\n"
        "python -m nltk.downloader stopwords punkt averaged_perceptron_tagger words"
    )

    try:
        from pyresparser import ResumeParser  # type: ignore

        return ResumeParser, None
    except Exception as initial_exc:
        initial_error = str(initial_exc)

    setup_steps = [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--user",
            "pyresparser",
            "spacy",
            "nltk",
        ],
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--user",
            "--break-system-packages",
            "pyresparser",
            "spacy",
            "nltk",
        ],
        [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
        [sys.executable, "-m", "nltk.downloader", "stopwords", "punkt", "averaged_perceptron_tagger", "words"],
    ]

    failed_steps: list[str] = []
    for command in setup_steps:
        ok, output = _run_setup_command(command)
        if not ok:
            tail = output[-260:] if output else "no output"
            failed_steps.append(f"{' '.join(command)} -> {tail}")

    try:
        from pyresparser import ResumeParser  # type: ignore

        return ResumeParser, None
    except Exception as final_exc:
        detail = (
            "External parser setup failed.\n"
            f"Initial import error: {initial_error}\n"
            f"Final import error: {final_exc}\n"
            f"Manual setup:\n{manual_hint}"
        )
        if failed_steps:
            detail += "\nSetup step failures:\n- " + "\n- ".join(failed_steps)
        return None, detail


def setup_ats_runtime_assets() -> list[str]:
    setup_steps = [
        [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
        [sys.executable, "-m", "nltk.downloader", "stopwords", "punkt", "averaged_perceptron_tagger", "words"],
    ]
    failed_steps: list[str] = []
    for command in setup_steps:
        ok, output = _run_setup_command(command)
        if not ok:
            tail = output[-260:] if output else "no output"
            failed_steps.append(f"{' '.join(command)} -> {tail}")
    return failed_steps


def has_useful_parsed_fields(parsed: dict[str, Any]) -> bool:
    for value in parsed.values():
        if isinstance(value, list):
            if value:
                return True
        elif value not in (None, "", {}, []):
            return True
    return False


def run_spacy_external_parser(resume_text: str) -> tuple[dict[str, Any], str | None]:
    import warnings

    try:
        import spacy  # type: ignore
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=r".*\[W094\].*", category=UserWarning)
            nlp = spacy.load("en_core_web_sm")
    except Exception:
        setup_ats_runtime_assets()
        try:
            import spacy  # type: ignore
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=r".*\[W094\].*", category=UserWarning)
                nlp = spacy.load("en_core_web_sm")
        except Exception as exc:
            return {}, f"spaCy fallback parser failed: {exc}"

    doc = nlp(resume_text)

    heading_match = re.search(r"^#\s+(.+?)$", resume_text, flags=re.MULTILINE)
    name: str | None = heading_match.group(1).strip() if heading_match else None
    if not name:
        for ent in doc.ents:
            if ent.label_ == "PERSON" and len(ent.text.split()) >= 2:
                name = ent.text.strip()
                break

    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", resume_text)
    email = email_match.group(0) if email_match else None

    mobile_number: str | None = None
    try:
        import phonenumbers  # type: ignore

        matches = list(phonenumbers.PhoneNumberMatcher(resume_text, None))
        if matches:
            mobile_number = phonenumbers.format_number(matches[0].number, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        phone_match = re.search(r"(\+?\d[\d\s\-().]{7,}\d)", resume_text)
        mobile_number = phone_match.group(1) if phone_match else None

    title_match = re.search(r"^\*\*(.*?)\*\*$", resume_text, flags=re.MULTILINE)
    designation = title_match.group(1).strip() if title_match else None

    exp_match = re.search(r"(\d{1,2})\+?\s+years", resume_text, flags=re.IGNORECASE)
    total_experience = float(exp_match.group(1)) if exp_match else None

    degree_match = re.search(
        r"(bachelor(?:'s)?|master(?:'s)?|phd|doctorate|mba|b\.sc|m\.sc|btech|mtech)",
        resume_text,
        flags=re.IGNORECASE,
    )
    degree = degree_match.group(1) if degree_match else None

    work_entries = parse_experience_entries(extract_section_body(resume_text, "Work Experience"))
    company_names = [str(entry.get("company", "")).strip() for entry in work_entries if str(entry.get("company", "")).strip()]
    if not company_names:
        company_names = [ent.text.strip() for ent in doc.ents if ent.label_ == "ORG"]
    company_names = list(dict.fromkeys(company_names))[:12]

    skills = extract_meaningful_tags(resume_text, max_tags=40)

    parsed: dict[str, Any] = {
        "name": name,
        "email": email,
        "mobile_number": mobile_number,
        "skills": skills,
        "total_experience": total_experience,
        "degree": degree,
        "designation": designation,
        "company_names": company_names,
    }
    return parsed, None


def run_external_ats_parser(resume_text: str, auto_setup: bool = True) -> tuple[str, dict[str, Any], str | None]:
    import warnings

    warnings.filterwarnings("ignore", message=r".*\[W094\].*", category=UserWarning)

    provider = "pyresparser"
    if auto_setup:
        ResumeParser, hint = load_pyresparser_with_autosetup()
    else:
        hint = None
        try:
            from pyresparser import ResumeParser  # type: ignore
        except Exception as exc:
            ResumeParser = None
            hint = f"pyresparser unavailable in quick mode: {exc}"

    if ResumeParser is None:
        fallback_parsed, fallback_hint = run_spacy_external_parser(resume_text)
        if has_useful_parsed_fields(fallback_parsed):
            return "spacy-ner", fallback_parsed, None
        merged_hint = hint or ""
        if fallback_hint:
            merged_hint = (merged_hint + "\n" + fallback_hint).strip()
        return provider, {}, merged_hint or None

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        temp_path = Path(handle.name)
        handle.write(resume_text)

    parse_hint: str | None = None
    try:
        parsed = ResumeParser(str(temp_path)).get_extracted_data() or {}
    except Exception as exc:  # pragma: no cover
        failed_runtime_steps = setup_ats_runtime_assets()
        try:
            parsed = ResumeParser(str(temp_path)).get_extracted_data() or {}
        except Exception as retry_exc:
            parse_hint = (
                f"External parser execution failed: {retry_exc}\n"
                "Try setup commands:\n"
                "python -m pip install --user pyresparser spacy nltk\n"
                "python -m pip install --user --break-system-packages pyresparser spacy nltk\n"
                "python -m spacy download en_core_web_sm\n"
                "python -m nltk.downloader stopwords punkt averaged_perceptron_tagger words"
            )
            if failed_runtime_steps:
                parse_hint += "\nRuntime setup failures:\n- " + "\n- ".join(failed_runtime_steps)
            parsed = {}
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass

    if has_useful_parsed_fields(parsed):
        return provider, parsed, None

    fallback_parsed, fallback_hint = run_spacy_external_parser(resume_text)
    if has_useful_parsed_fields(fallback_parsed):
        return "spacy-ner", fallback_parsed, None

    merged_hint = parse_hint or ""
    if fallback_hint:
        merged_hint = (merged_hint + "\n" + fallback_hint).strip()
    return provider, parsed, merged_hint or None


def cmd_ats(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    resume = ensure_resume_exists(root, state)
    resume_text = read_text(resume)

    provider, parsed, hint = run_external_ats_parser(resume_text, auto_setup=True)

    print(f"ATS source: {provider} (external)")
    if hint is not None:
        print("External parser not ready or failed in current environment.")
        print(hint)

    fields = {
        "name": parsed.get("name") if parsed else None,
        "email": parsed.get("email") if parsed else None,
        "mobile_number": parsed.get("mobile_number") if parsed else None,
        "skills": parsed.get("skills") if parsed else None,
        "total_experience": parsed.get("total_experience") if parsed else None,
        "degree": parsed.get("degree") if parsed else None,
        "designation": parsed.get("designation") if parsed else None,
        "company_names": parsed.get("company_names") if parsed else None,
    }

    if args:
        profile = args[0].strip().lower()
        if profile in {"senior", "sr", "staff", "lead", "principal"}:
            senior_terms = r"\b(senior|sr\.?|staff|lead|principal|architect|head|manager)\b"
            leadership_terms = r"\b(lead|led|mentor|mentored|ownership|architect|architecture|strategy|roadmap|stakeholder)\b"
            senior_skill_pool = {
                "typescript", "javascript", "react", "next.js", "node.js", "graphql", "aws", "docker", "kubernetes", "ci/cd",
            }

            designation = str(fields.get("designation") or "")
            total_experience = fields.get("total_experience")
            years = 0.0
            if isinstance(total_experience, (int, float)):
                years = float(total_experience)
            else:
                years_match = re.search(r"(\d{1,2})\+?\s+years", resume_text, flags=re.IGNORECASE)
                years = float(years_match.group(1)) if years_match else 0.0

            work_entries = parse_experience_entries(extract_section_body(resume_text, "Work Experience"))
            dated_entries = [
                row
                for row in work_entries
                if isinstance(row.get("start_m"), int) and isinstance(row.get("end_m"), int)
            ]
            if years <= 0 and dated_entries:
                intervals = sorted((int(row["start_m"]), int(row["end_m"])) for row in dated_entries)
                merged: list[list[int]] = []
                for start_m, end_m in intervals:
                    if not merged or start_m > merged[-1][1]:
                        merged.append([start_m, end_m])
                    else:
                        merged[-1][1] = max(merged[-1][1], end_m)
                total_months = sum(end_m - start_m for start_m, end_m in merged)
                years = (total_months / 12) if total_months > 0 else 0.0

            normalized = resume_text.lower()
            title_signal = bool(re.search(senior_terms, f"{designation} {normalized}", flags=re.IGNORECASE))
            leadership_signal = bool(re.search(leadership_terms, normalized, flags=re.IGNORECASE))

            extracted_skills = set()
            if isinstance(fields.get("skills"), list):
                extracted_skills = {normalize_tag(str(item)) for item in fields.get("skills") or [] if str(item).strip()}
            if not extracted_skills:
                extracted_skills = set(extract_meaningful_tags(resume_text, max_tags=60))

            skill_overlap = sorted(skill for skill in senior_skill_pool if skill in extracted_skills)
            company_count = len(fields.get("company_names") or []) if isinstance(fields.get("company_names"), list) else 0
            if company_count == 0 and work_entries:
                company_count = len({str(row.get("company", "")).strip().lower() for row in work_entries if str(row.get("company", "")).strip()})

            checks: list[tuple[str, bool, str]] = [
                ("Experience >= 5 years", years >= 5.0, f"detected: {years:.1f}"),
                ("Seniority title signal", title_signal, f"designation: {designation or 'none'}"),
                ("Leadership signal", leadership_signal, "keywords in resume"),
                ("Core senior skill overlap >= 4", len(skill_overlap) >= 4, f"matched: {', '.join(skill_overlap) if skill_overlap else 'none'}"),
                ("Multi-company history >= 2", company_count >= 2, f"detected companies: {company_count}"),
            ]

            passed = sum(1 for _, ok, _ in checks if ok)
            score = int(round((passed / len(checks)) * 100))

            print("ATS profile filter: senior")
            print(f"Source: {provider}")
            print(f"Filter score: {score}/100")
            print("Checks:")
            for label, ok, detail in checks:
                print(f"- {'PASS' if ok else 'FAIL'} | {label} | {detail}")
            print("Decision: " + ("PASS" if passed >= 4 else "REVIEW" if passed >= 3 else "FAIL"))
            return 0

        die("Usage: cv ats [senior]")

    present = 0
    for value in fields.values():
        if isinstance(value, list):
            if value:
                present += 1
        elif value not in (None, "", []):
            present += 1

    parser_score = int(round((present / len(fields)) * 100)) if fields else 0

    required_sections = ["Summary", "Work Experience", "Skills", "Education", "Languages"]
    missing_sections = [section for section in required_sections if not section_exists(resume_text, section)]

    structure_score = 100 - (len(missing_sections) * 12)
    if structure_score < 0:
        structure_score = 0

    final_score = int(round((parser_score * 0.7) + (structure_score * 0.3)))

    print("Non-AI ATS parser report")
    print(f"External parser field score: {parser_score}/100")
    print(f"Structure score: {structure_score}/100")
    print(f"Combined score: {final_score}/100")
    print(f"Required sections missing: {', '.join(missing_sections) if missing_sections else 'none'}")

    for key, value in fields.items():
        if isinstance(value, list):
            preview = ", ".join(str(item) for item in value[:8]) if value else "none"
        else:
            preview = str(value) if value else "none"
        print(f"{key}: {preview}")

    if shutil.which("copilot"):
        prompt = (
            "You are ATS expert. Provide short but detailed scoring and advice.\n"
            f"External ATS source: {provider}\n"
            f"External parsed fields JSON: {json.dumps(fields)}\n"
            f"Structure score: {structure_score}\n"
            f"Combined score: {final_score}\n"
            f"Resume markdown:\n{resume_text}\n"
            "Return:\n"
            "1) AI score out of 100.\n"
            "2) Top 5 fixes by impact.\n"
            "3) One concise rewritten Summary section."
        )
        print("\nAI ATS review")
        try:
            run_copilot(prompt)
        except subprocess.CalledProcessError:
            warn("AI ATS review failed. Non-AI report still valid.")
    else:
        warn("copilot CLI not found. Skipped AI ATS review.")

    return 0


def cmd_version(args: list[str]) -> int:
    del args
    print(f"cv {CV_VERSION}")
    return 0


def dispatch(cmd: str, args: list[str]) -> int:
    if cmd in {"help", "-h", "--help"}:
        return cmd_help()
    if cmd in {"version", "-v", "--version"}:
        return cmd_version(args)
    if cmd == "init":
        return cmd_init(args)
    if cmd == "install":
        return cmd_install(args)
    if cmd == "current":
        return cmd_current(args)
    if cmd == "jobs":
        return cmd_jobs(args)
    if cmd == "title":
        return cmd_title(args)
    if cmd == "section":
        return cmd_section(args)
    if cmd == "skills":
        return cmd_skills(args)
    if cmd == "exp":
        return cmd_exp(args)
    if cmd == "tags":
        return cmd_tags(args)
    if cmd == "say":
        return cmd_say(args)
    if cmd == "fit":
        return cmd_fit(args)
    if cmd == "tailor":
        return cmd_tailor(args)
    if cmd == "track":
        return cmd_track(args)
    if cmd == "posts":
        return cmd_posts(args)
    if cmd == "auto":
        return cmd_auto(args)
    if cmd == "ats":
        return cmd_ats(args)
    if cmd == "ci":
        return cmd_ci(args)

    die(f"Unknown command: {cmd}. Run: cv help")
    return 1


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        return cmd_help()

    cmd = argv[0]
    args = argv[1:]
    return dispatch(cmd, args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CVError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
