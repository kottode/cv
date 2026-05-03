from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

from ...errors import die, warn
from ...internal import llm, web
from ...internal.ats import ats_enrichment_text, run_external_ats_parser
from ...internal.project import ensure_resume_exists, load_state, read_text, require_project
from ...internal.resume_analysis import (
    analyze_job_fit as analyze_job_fit_internal,
    fit_grade as fit_grade_internal,
    keyword_filter_reason as keyword_filter_reason_internal,
    keywords_from_text,
    parse_experience_entries,
)


def fit_grade(score: int) -> str:
    return fit_grade_internal(score)


def analyze_job_fit(job_text: str, resume_keywords: set[str]) -> dict[str, Any]:
    return analyze_job_fit_internal(job_text, resume_keywords)


def keyword_filter_reason(job_text: str, include_keywords: list[str], exclude_keywords: list[str]) -> str:
    return keyword_filter_reason_internal(job_text, include_keywords, exclude_keywords)


def cmd_fit(args: list[str]) -> int:
    if not args:
        die("Usage: cv fit <text|url>")

    root = require_project()
    state = load_state(root)
    resume = ensure_resume_exists(root, state)

    user_input = " ".join(args).strip()
    source_kind, source_value, job_text = web.resolve_job_text(user_input)

    job_text = re.sub(r"\s+", " ", job_text).strip()
    if not job_text:
        die("Job description is empty")
    if len(job_text) > 12000:
        job_text = job_text[:12000]

    resume_text = read_text(resume)
    provider, parsed, hint = run_external_ats_parser(
        resume_text,
        auto_setup=False,
        parse_experience_entries=parse_experience_entries,
    )
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
            llm.run(prompt)
        except subprocess.CalledProcessError:
            warn("AI fit review failed. Non-AI precheck still valid.")
    else:
        warn("copilot CLI not found. Skipped AI fit review.")

    return 0
