from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

SectionBodyExtractor = Callable[[str, str], str]
ExperienceEntryParser = Callable[[str], list[dict[str, Any]]]
MeaningfulTagExtractor = Callable[[str, int], list[str]]


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


def _run_setup_command(command: list[str]) -> tuple[bool, str]:
    env = os.environ.copy()
    env.setdefault("PIP_BREAK_SYSTEM_PACKAGES", "1")
    proc = subprocess.run(command, text=True, capture_output=True, env=env)
    output = (proc.stdout + "\n" + proc.stderr).strip()
    return proc.returncode == 0, output


def _in_virtualenv() -> bool:
    return (getattr(sys, "base_prefix", sys.prefix) != sys.prefix) or bool(os.environ.get("VIRTUAL_ENV"))


def _manual_setup_hint() -> str:
    if _in_virtualenv():
        return (
            f"{sys.executable} -m pip install pyresparser spacy nltk phonenumbers\n"
            f"{sys.executable} -m spacy download en_core_web_sm\n"
            f"{sys.executable} -m nltk.downloader stopwords punkt averaged_perceptron_tagger words"
        )
    return (
        "python -m pip install --user pyresparser spacy nltk phonenumbers\n"
        "python -m pip install --user --break-system-packages pyresparser spacy nltk phonenumbers\n"
        "python -m spacy download en_core_web_sm\n"
        "python -m nltk.downloader stopwords punkt averaged_perceptron_tagger words"
    )


def _pip_install_setup_steps() -> list[list[str]]:
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    packages = ["pyresparser", "spacy", "nltk", "phonenumbers"]
    if _in_virtualenv():
        return [base + packages]
    return [
        base + ["--user"] + packages,
        base + ["--user", "--break-system-packages"] + packages,
    ]


def load_pyresparser_with_autosetup() -> tuple[Any | None, str | None]:
    manual_hint = _manual_setup_hint()

    try:
        from pyresparser import ResumeParser  # type: ignore

        return ResumeParser, None
    except Exception as initial_exc:
        initial_error = str(initial_exc)

    setup_steps = [
        *_pip_install_setup_steps(),
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


def run_spacy_external_parser(
    resume_text: str,
    *,
    extract_section_body: SectionBodyExtractor,
    parse_experience_entries: ExperienceEntryParser,
    extract_meaningful_tags: MeaningfulTagExtractor,
) -> tuple[dict[str, Any], str | None]:
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

    skills = extract_meaningful_tags(resume_text, 40)

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


def run_external_ats_parser(
    resume_text: str,
    auto_setup: bool = True,
    *,
    extract_section_body: SectionBodyExtractor,
    parse_experience_entries: ExperienceEntryParser,
    extract_meaningful_tags: MeaningfulTagExtractor,
) -> tuple[str, dict[str, Any], str | None]:
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
        fallback_parsed, fallback_hint = run_spacy_external_parser(
            resume_text,
            extract_section_body=extract_section_body,
            parse_experience_entries=parse_experience_entries,
            extract_meaningful_tags=extract_meaningful_tags,
        )
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
    except Exception:  # pragma: no cover
        failed_runtime_steps = setup_ats_runtime_assets()
        try:
            parsed = ResumeParser(str(temp_path)).get_extracted_data() or {}
        except Exception as retry_exc:
            parse_hint = (
                f"External parser execution failed: {retry_exc}\n"
                "Try setup commands:\n"
                f"{_manual_setup_hint()}"
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

    fallback_parsed, fallback_hint = run_spacy_external_parser(
        resume_text,
        extract_section_body=extract_section_body,
        parse_experience_entries=parse_experience_entries,
        extract_meaningful_tags=extract_meaningful_tags,
    )
    if has_useful_parsed_fields(fallback_parsed):
        return "spacy-ner", fallback_parsed, None

    merged_hint = parse_hint or ""
    if fallback_hint:
        merged_hint = (merged_hint + "\n" + fallback_hint).strip()
    return provider, parsed, merged_hint or None
