from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import urllib.parse

from ...errors import die, warn
from ...internal.ats import ats_fields_subset, run_external_ats_parser
from ...internal.llm import run
from ...internal.project import extract_section_body, ensure_resume_exists, load_state, read_text, require_project
from ...internal.resume_analysis import extract_meaningful_tags, parse_experience_entries, resolve_job_text_argument
from ...utils import slugify


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
    provider, parsed, hint = run_external_ats_parser(
        base_text,
        auto_setup=False,
        extract_section_body=extract_section_body,
        parse_experience_entries=parse_experience_entries,
        extract_meaningful_tags=extract_meaningful_tags,
    )
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
            tailored = run(prompt, capture=True)
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
