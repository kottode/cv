from __future__ import annotations

import json
import re
import shutil
import subprocess

from ...errors import die, warn
from ...internal import llm
from ...internal.ats import run_external_ats_parser
from ...internal.project import extract_section_body, load_state, require_project, section_exists, ensure_resume_exists, read_text
from ...internal.resume_analysis import extract_meaningful_tags, normalize_tag, parse_experience_entries


def cmd_ats(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    resume = ensure_resume_exists(root, state)
    resume_text = read_text(resume)

    provider, parsed, hint = run_external_ats_parser(
        resume_text,
        auto_setup=True,
        extract_section_body=extract_section_body,
        parse_experience_entries=parse_experience_entries,
        extract_meaningful_tags=extract_meaningful_tags,
    )

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
            llm.run(prompt)
        except subprocess.CalledProcessError:
            warn("AI ATS review failed. Non-AI report still valid.")
    else:
        warn("copilot CLI not found. Skipped AI ATS review.")

    return 0
