from __future__ import annotations

import re


_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(ignore|disregard|forget)\b.{0,50}\b(previous|above|earlier|system|instructions?|prompt)\b", re.IGNORECASE),
    re.compile(r"\b(system prompt|developer message|assistant message|hidden prompt)\b", re.IGNORECASE),
    re.compile(r"\b(reveal|leak|expose|print|dump)\b.{0,40}\b(prompt|instructions?|secrets?|chain[ -]?of[ -]?thought|cot)\b", re.IGNORECASE),
    re.compile(r"\b(do not|don't)\b.{0,20}\b(follow|obey)\b.{0,40}\b(instructions?|rules|prompt)\b", re.IGNORECASE),
    re.compile(r"\b(jailbreak|dan mode|prompt injection)\b", re.IGNORECASE),
    re.compile(r"\b(tool call|function call|execute command|run shell|bash -c|curl http)\b", re.IGNORECASE),
)

_ROLE_PREFIX = re.compile(r"^\s*(system|assistant|developer|tool)\s*:\s*", re.IGNORECASE)


def detect_prompt_injection_signals(text: str, max_signals: int = 8) -> list[str]:
    lowered = text or ""
    signals: list[str] = []
    seen: set[str] = set()
    for pattern in _INJECTION_PATTERNS:
        for match in pattern.finditer(lowered):
            snippet = match.group(0).strip()
            if not snippet:
                continue
            key = snippet.lower()
            if key in seen:
                continue
            seen.add(key)
            signals.append(snippet)
            if len(signals) >= max_signals:
                return signals
    return signals


def sanitize_untrusted_job_text(text: str, max_chars: int = 12000) -> dict[str, object]:
    source = (text or "").replace("\x00", " ").replace("\r", "\n")
    source = re.sub(r"\n{3,}", "\n\n", source)

    kept_lines: list[str] = []
    removed_lines = 0

    for raw_line in source.split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            kept_lines.append("")
            continue

        if _ROLE_PREFIX.match(line):
            removed_lines += 1
            continue

        if any(pattern.search(line) for pattern in _INJECTION_PATTERNS):
            removed_lines += 1
            continue

        kept_lines.append(line)

    cleaned = "\n".join(kept_lines).strip()
    if not cleaned:
        cleaned = re.sub(r"\s+", " ", source).strip()

    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]

    return {
        "cleaned": cleaned,
        "removed_lines": removed_lines,
        "signals": detect_prompt_injection_signals(source),
    }
