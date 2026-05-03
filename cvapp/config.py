from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

CV_VERSION = "0.2.0"
DEFAULT_MODEL = "gpt-5-mini"
STATE_DIR = Path(".cv")
STATE_FILE = STATE_DIR / "state.env"
LEGACY_TRACK_FILE = STATE_DIR / "track.tsv"
TRACK_FILE_NAME = "track.tsv"
POSTS_FILE_NAME = "posts.json"
AUTO_CONFIG_FILE = STATE_DIR / "auto.env"
TELEGRAM_CONFIG_FILE = Path.home() / ".config" / "cv" / "telegram.env"
TELEGRAM_SETUP_TEST_MESSAGE = "cv telegram integration connected"

TAG_STOPWORDS = {
    "and", "the", "for", "with", "from", "that", "this", "your", "you", "into", "over", "under", "about",
    "have", "has", "had", "are", "was", "were", "will", "would", "can", "could", "should", "our", "their",
    "its", "via", "using", "use", "used", "per", "plus", "year", "years", "month", "months", "present",
    "current", "work", "experience", "summary", "skills", "education", "languages", "add", "measurable", "impact",
    "team", "role", "company", "candidate", "professional", "title", "job", "responsibilities",
}

TECH_TAG_PATTERNS: list[tuple[str, str]] = [
    ("typescript", r"\btypescript\b"),
    ("javascript", r"\bjavascript\b"),
    ("react", r"\breact(?:\.js)?\b"),
    ("next.js", r"\bnext\.js\b|\bnextjs\b"),
    ("nestjs", r"\bnest\.js\b|\bnestjs\b"),
    ("node.js", r"\bnode(?:\.js)?\b"),
    ("vue", r"\bvue(?:\.js)?\b"),
    ("angular", r"\bangular\b"),
    ("svelte", r"\bsvelte\b"),
    ("redux", r"\bredux\b"),
    ("graphql", r"\bgraphql\b"),
    ("rest api", r"\brest(?:ful)?\b|\bapi\b"),
    ("docker", r"\bdocker\b"),
    ("kubernetes", r"\bkubernetes\b|\bk8s\b"),
    ("aws", r"\baws\b|\bamazon web services\b"),
    ("gcp", r"\bgcp\b|\bgoogle cloud\b"),
    ("azure", r"\bazure\b"),
    ("ci/cd", r"\bci/?cd\b|\bcontinuous integration\b|\bcontinuous delivery\b"),
    ("github actions", r"\bgithub actions\b"),
    ("gitlab ci", r"\bgitlab\b"),
    ("jenkins", r"\bjenkins\b"),
    ("terraform", r"\bterraform\b"),
    ("ansible", r"\bansible\b"),
    ("sql", r"\bsql\b"),
    ("postgresql", r"\bpostgres(?:ql)?\b"),
    ("mysql", r"\bmysql\b"),
    ("mongodb", r"\bmongodb\b"),
    ("redis", r"\bredis\b"),
    ("kafka", r"\bkafka\b"),
    ("rabbitmq", r"\brabbitmq\b"),
    ("grpc", r"\bgrpc\b"),
    ("microservices", r"\bmicroservice(?:s)?\b"),
    ("linux", r"\blinux\b"),
    ("bash", r"\bbash\b|\bshell scripting\b"),
    ("python", r"\bpython\b"),
    ("django", r"\bdjango\b"),
    ("flask", r"\bflask\b"),
    ("fastapi", r"\bfastapi\b"),
    ("java", r"\bjava\b"),
    ("spring", r"\bspring\b"),
    ("c#", r"\bc#\b|\bdotnet\b|\.net"),
    ("c++", r"\bc\+\+\b"),
    ("go", r"\bgolang\b|\bgo\b"),
    ("rust", r"\brust\b"),
    ("php", r"\bphp\b"),
    ("laravel", r"\blaravel\b"),
    ("html", r"\bhtml\b"),
    ("css", r"\bcss\b"),
    ("sass", r"\bsass\b|\bscss\b"),
    ("tailwind", r"\btailwind\b"),
    ("webpack", r"\bwebpack\b"),
    ("vite", r"\bvite\b"),
    ("jest", r"\bjest\b"),
    ("cypress", r"\bcypress\b"),
    ("playwright", r"\bplaywright\b"),
    ("testing library", r"\btesting library\b"),
    ("storybook", r"\bstorybook\b"),
    ("figma", r"\bfigma\b"),
    ("accessibility", r"\baccessibility\b|\bwcag\b|\ba11y\b"),
    ("performance", r"\bperformance\b|\bweb vitals\b"),
]

NOISY_TAG_TOKENS = {
    "yyyy", "mm", "here", "goes", "add", "candidate", "summary", "impact", "skill", "skills",
}

SHORT_TAG_ALLOWLIST = {"go", "ui", "ux", "qa", "ai", "ml", "bi", "aws", "gcp", "c#"}
COMPOSITE_KEEP_TAGS = {"ci/cd", "ui/ux", "r&d", "b2b", "b2c"}


@dataclass
class CVState:
    current_job: str = "default"
    current_name: str = "resume"
    current_title: str = "Professional Title"


@dataclass
class AutoConfig:
    enabled: bool = False
    search_urls: list[str] = field(default_factory=list)
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    min_score: int = 60
    max_posts: int = 12
    max_links_per_seed: int = 25
    auto_apply: bool = True
    notify: bool = True
    last_run_at: str = ""
    last_seeked: int = 0
    last_parsed: int = 0
    last_filtered: int = 0
    last_stored: int = 0
    last_applied: int = 0
    last_error: str = ""
