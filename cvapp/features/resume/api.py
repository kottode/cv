from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ...config import CVState, STATE_DIR
from ...errors import die, warn
from ...internal.ats import ats_enrichment_text, run_external_ats_parser
from ...internal.project import (
    current_resume_path,
    ensure_resume_exists,
    extract_section_body,
    load_state,
    normalize_section_name,
    read_text,
    replace_section_body,
    require_project,
    save_state,
    section_exists,
    write_text,
)
from ...internal.resume_analysis import (
    build_tags_from_resume,
    extract_meaningful_tags,
    merge_unique_tags,
    parse_experience_entries,
    resolve_job_text_argument,
)
from ...internal.storage import ensure_track_file
from ...internal.system import editor_command, remove_prompt_hook
from ...utils import slugify


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
        provider, parsed, hint = run_external_ats_parser(
            text,
            auto_setup=False,
            extract_section_body=extract_section_body,
            parse_experience_entries=parse_experience_entries,
            extract_meaningful_tags=extract_meaningful_tags,
        )

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

        target_words = {word for word in words(target_title) if len(word) > 1}

        entries.sort(key=lambda row: row.get("start_m") if isinstance(row.get("start_m"), int) else -1, reverse=True)
        print("#  Company | Title | Range | Relevance")
        for idx, row in enumerate(entries, start=1):
            title_words = {word for word in words(row["title"]) if len(word) > 1}
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


def cmd_tags(args: list[str]) -> int:
    root = require_project()
    state = load_state(root)
    resume = ensure_resume_exists(root, state)
    text = read_text(resume)

    resume_tags = build_tags_from_resume(text)
    provider, parsed, hint = run_external_ats_parser(
        text,
        auto_setup=False,
        extract_section_body=extract_section_body,
        parse_experience_entries=parse_experience_entries,
        extract_meaningful_tags=extract_meaningful_tags,
    )
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
