from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser

from ..errors import die, warn
from .resume_analysis import keywords_from_text as analysis_keywords_from_text


class PrimaryTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_stack: list[bool] = []
        self.in_main = 0
        self.main_parts: list[str] = []
        self.parts: list[str] = []

    def _active_skip(self) -> bool:
        return bool(self.skip_stack and self.skip_stack[-1])

    @staticmethod
    def _is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
        attrs_map = {k.lower(): (v or "") for k, v in attrs}
        if "hidden" in attrs_map:
            return True
        style = attrs_map.get("style", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            return True
        if attrs_map.get("aria-hidden", "").lower() == "true":
            return True
        if attrs_map.get("type", "").lower() == "hidden":
            return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        skip_tags = {
            "script", "style", "noscript", "header", "footer", "nav", "aside", "form",
            "input", "button", "select", "option", "textarea", "svg", "canvas", "iframe",
            "img", "picture", "video", "audio",
        }
        block_tags = {
            "main", "article", "section", "div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr",
        }

        tag = tag.lower()
        parent_skip = self._active_skip()
        this_skip = parent_skip or tag in skip_tags or self._is_hidden(attrs)
        self.skip_stack.append(this_skip)

        if this_skip:
            return

        if tag == "main":
            self.in_main += 1

        if tag in block_tags:
            self._append("\n")

    def handle_endtag(self, tag: str) -> None:
        block_tags = {
            "main", "article", "section", "div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr",
        }

        tag = tag.lower()
        if not self.skip_stack:
            return
        this_skip = self.skip_stack.pop()

        if not this_skip and tag == "main" and self.in_main > 0:
            self.in_main -= 1

        if not this_skip and tag in block_tags:
            self._append("\n")

    def handle_data(self, data: str) -> None:
        if self._active_skip():
            return
        text = re.sub(r"\s+", " ", data).strip()
        if text:
            self._append(text)

    def _append(self, value: str) -> None:
        if self.in_main > 0:
            self.main_parts.append(value)
        self.parts.append(value)


def normalize_url(url: str) -> str:
    raw = url.strip()
    if not raw:
        return ""

    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        return raw

    filtered_pairs: list[tuple[str, str]] = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False):
        key_l = key.lower()
        if key_l.startswith("utm_") or key_l in {"gclid", "fbclid", "trk", "tracking", "source"}:
            continue
        filtered_pairs.append((key, value))

    clean_path = parsed.path or "/"
    if clean_path != "/":
        clean_path = clean_path.rstrip("/") or "/"

    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            clean_path,
            "",
            urllib.parse.urlencode(filtered_pairs),
            "",
        )
    )


def fetch_html(url: str) -> tuple[bool, str, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read()
    except Exception as exc:
        return False, "", "", str(exc)

    charset_match = re.search(r"charset=([A-Za-z0-9_-]+)", content_type)
    encoding = charset_match.group(1) if charset_match else "utf-8"
    html = raw.decode(encoding, errors="replace")
    return True, html, content_type, ""


def extract_primary_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
    except Exception as exc:
        die(f"URL fetch error: {exc}")

    charset_match = re.search(r"charset=([A-Za-z0-9_-]+)", content_type)
    encoding = charset_match.group(1) if charset_match else "utf-8"
    html = raw.decode(encoding, errors="replace")

    if "html" not in content_type.lower() and "<html" not in html[:2000].lower():
        plain = re.sub(r"\s+", " ", html).strip()
        return plain[:20000]

    candidates: list[str] = []
    jsonld = extract_jsonld(html)
    if jsonld.strip():
        candidates.append(jsonld)

    embedded = extract_script_embedded(html)
    if embedded.strip():
        candidates.append(embedded)

    parser = PrimaryTextParser()
    parser.feed(html)

    main_text = "\n".join(parser.main_parts)
    all_text = "\n".join(parser.parts)
    chosen = main_text if len(main_text) >= 300 else all_text
    chosen = re.sub(r"\n{3,}", "\n\n", chosen)
    chosen_lines = [re.sub(r"\s+", " ", line).strip() for line in chosen.splitlines()]
    chosen_lines = [line for line in chosen_lines if len(line) >= 20]
    chosen_text = "\n".join(chosen_lines).strip()
    if chosen_text:
        candidates.append(chosen_text)

    plain = strip_html_tags(html)
    if plain:
        candidates.append(plain)

    best = ""
    for candidate in candidates:
        candidate = candidate.strip()
        if len(candidate) > len(best):
            best = candidate

    return best[:20000]


def extract_links(base_url: str, html: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE):
        href = raw.strip()
        if not href or href.startswith("#"):
            continue
        if href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue

        absolute = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme.lower() not in {"http", "https"}:
            continue

        normalized = normalize_url(absolute)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)
    return links


def discover_job_urls(seed_url: str, max_links: int) -> list[str]:
    normalized_seed = normalize_url(seed_url)
    if not normalized_seed:
        return []

    urls: list[str] = []
    if looks_like_job_url(normalized_seed):
        urls.append(normalized_seed)

    ok, html, content_type, error = fetch_html(normalized_seed)
    if not ok:
        warn(f"auto: seed fetch failed for {normalized_seed}: {error}")
        return urls or [normalized_seed]

    html_like = "html" in content_type.lower() or "<html" in html[:2000].lower()
    if not html_like:
        return urls or [normalized_seed]

    candidates = extract_links(normalized_seed, html)
    for candidate in candidates:
        if looks_like_job_url(candidate):
            urls.append(candidate)

    if not urls:
        urls.append(normalized_seed)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in urls:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
        if len(deduped) >= max_links:
            break
    return deduped


def extract_jsonld(html: str) -> str:
    chunks: list[str] = []
    pattern = re.compile(r"<script[^>]*type=[\"']application/ld\\+json[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)

    def collect(obj) -> None:
        if isinstance(obj, dict):
            for key in ["title", "description", "responsibilities", "qualifications"]:
                value = obj.get(key)
                if isinstance(value, str):
                    cleaned = strip_html_tags(value)
                    if len(cleaned) > 30:
                        chunks.append(cleaned)
            for value in obj.values():
                collect(value)
        elif isinstance(obj, list):
            for item in obj:
                collect(item)

    for match in pattern.finditer(html):
        payload = match.group(1).strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        collect(data)

    return "\n".join(dict.fromkeys(chunks))


def extract_script_embedded(html: str) -> str:
    chunks: list[str] = []
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL)

    patterns = [
        r'"jobDescription"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"description"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"responsibilities"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"qualifications"\s*:\s*"((?:\\.|[^"\\])*)"',
    ]

    for script in scripts:
        lowered = script.lower()
        if "description" not in lowered and "job" not in lowered:
            continue
        for pattern in patterns:
            for raw in re.findall(pattern, script, flags=re.IGNORECASE | re.DOTALL):
                try:
                    decoded = bytes(raw, "utf-8").decode("unicode_escape")
                except UnicodeDecodeError:
                    decoded = raw
                cleaned = strip_html_tags(decoded)
                if len(cleaned) > 60:
                    chunks.append(cleaned)

    return "\n".join(dict.fromkeys(chunks))


def strip_html_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def looks_like_job_url(url: str) -> bool:
    lowered = url.lower()
    markers = [
        "job", "jobs", "career", "careers", "position", "positions", "opening", "openings", "opportunity",
        "greenhouse", "lever", "workday", "ashby", "smartrecruiters", "icims", "recruit",
    ]
    return any(marker in lowered for marker in markers)


def keywords_from_text(text: str, top_n: int = 40) -> list[str]:
    return analysis_keywords_from_text(text, top_n=top_n)


def resolve_job_text(raw_input: str) -> tuple[str, str, str]:
    source_value = raw_input.strip()
    if re.match(r"^https?://", source_value, flags=re.IGNORECASE):
        return "url", source_value, extract_primary_text(source_value)
    return "text", source_value, source_value
