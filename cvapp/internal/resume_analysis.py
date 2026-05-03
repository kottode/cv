from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from collections import Counter
from typing import Any

from ..config import COMPOSITE_KEEP_TAGS, NOISY_TAG_TOKENS, SHORT_TAG_ALLOWLIST, TAG_STOPWORDS, TECH_TAG_PATTERNS
from ..internal.project import extract_section_body
from ..utils import normalize_tag, pretty_name, slugify


def month_index(value: str) -> int | None:
    match = re.fullmatch(r"([0-9]{4})-([0-9]{2})", value.strip())
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if month < 1 or month > 12:
        return None
    return year * 12 + month


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


def parse_date_range(value: str) -> tuple[str, str, int, int] | None:
    cleaned = re.sub(r"\s+", " ", value.strip())
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
            if not stripped or stripped.startswith("- ") or stripped.startswith("* "):
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
        if not tokens or len(tokens) > 4:
            return
        if tag in company_blacklist or tag in TAG_STOPWORDS:
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
        from .web import extract_primary_text

        return "url", source_value, extract_primary_text(source_value)
    return "text", source_value, source_value


def keywords_from_text(text: str, top_n: int = 40) -> list[str]:
    return extract_meaningful_tags(text, max_tags=top_n)


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
