from __future__ import annotations

import os
import re
from pathlib import Path

from ..config import POSTS_FILE_NAME, STATE_FILE, TRACK_FILE_NAME, CVState
from ..errors import die
from ..utils import pretty_name, quote_env, unquote_env


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

    if not updated.endswith("\n"):
        updated += "\n"
    return updated


def section_exists(text: str, section: str) -> bool:
    return re.search(rf"^## {re.escape(section)}$", text, flags=re.MULTILINE) is not None
