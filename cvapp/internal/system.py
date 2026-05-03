from __future__ import annotations

import os
import re
from pathlib import Path


def editor_command() -> str:
    return os.environ.get("EDITOR", "vi")


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
