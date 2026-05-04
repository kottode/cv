from __future__ import annotations

import subprocess
from pathlib import Path
import shutil

from ...errors import die, warn
from ...internal.project import current_resume_path, ensure_resume_exists, load_state, require_project
from ...strings import USAGE_GEN


def _ats_template_path() -> Path:
    return Path(__file__).resolve().parents[2] / "internal" / "ats_pdf_template.tex"


def _collect_markdown_targets(root: Path, args: list[str]) -> list[Path]:
    state = load_state(root)

    if not args:
        current_resume = ensure_resume_exists(root, state)
        return [current_resume]

    target = args[0].strip()
    if target.lower() == "all":
        paths = sorted(path for path in root.rglob("*.md") if path.is_file())
        return [path for path in paths if ".cv" not in path.parts]

    rel = Path(target)
    if not rel.is_absolute():
        rel = root / rel

    if rel.is_file() and rel.suffix.lower() == ".md":
        return [rel]

    if rel.is_dir():
        return sorted(path for path in rel.rglob("*.md") if path.is_file())

    if target.lower() == "current":
        return [root / current_resume_path(state)]

    die(USAGE_GEN)
    return []


def _pdf_path(markdown_path: Path) -> Path:
    return markdown_path.with_suffix(".pdf")


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def _gen_pdf(markdown_path: Path, pdf_path: Path) -> bool:
    template_path = _ats_template_path()
    if not template_path.is_file():
        warn("ATS PDF template missing. Reinstall cv and retry.")
        return False

    proc = subprocess.run(
        [
            "pandoc",
            "--standalone",
            "--pdf-engine=lualatex",
            "--template",
            str(template_path),
            str(markdown_path),
            "-o",
            str(pdf_path),
        ],
        text=True,
        capture_output=True,
    )
    if proc.returncode == 0:
        return True

    stderr = (proc.stderr or "").strip()
    if stderr:
        warn(f"Failed to generate {pdf_path.name}: {stderr}")
    else:
        warn(f"Failed to generate {pdf_path.name}")
    return False


def cmd_gen(args: list[str]) -> int:
    root = require_project()

    if shutil.which("pandoc") is None:
        die("pandoc is required for PDF generation. Install pandoc and try again.")
    if shutil.which("lualatex") is None:
        die("lualatex is required for PDF generation. Run ./install.sh to install dependencies.")

    targets = _collect_markdown_targets(root, args)
    if not targets:
        print("No markdown files found.")
        return 0

    generated = 0
    for md_path in targets:
        pdf_path = _pdf_path(md_path)
        if _gen_pdf(md_path, pdf_path):
            generated += 1
            print(f"Generated: {_display_path(root, pdf_path)}")

    print(f"PDF generated: {generated}/{len(targets)}")
    return 0 if generated > 0 else 1
