from __future__ import annotations

from ...errors import die
from ...internal.llm import run
from ...internal.project import ensure_resume_exists, load_state, require_project


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
    run(prompt)
    return 0
