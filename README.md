# cv

Resume CLI for init, profile switching, section management, tailoring, ATS checks, and application tracking.

`cv` now uses a Python core (`cv_core.py`) for maintainability, while keeping the same `cv` command.

## Install

```bash
./install.sh
```

Optional dependencies:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-ats.txt
```

Default install target is `~/.local/bin/cv`.

## Quick Start

```bash
cd /path/to/your/resume/project
cv init john-bang-gang
cv jobs frontend
cv title Frontend Developer
```

## Development Process

Use this flow when adding or changing commands:

- Define command behavior and input/output format first.
- Implement command logic in `cv_core.py` and keep `cv` as a thin entry wrapper.
- Keep command names and existing behavior stable unless intentionally changed.
- Run fast local checks:

```bash
python3 -m py_compile cv cv_core.py
./cv help
```

- Run feature smoke tests for changed commands (text, URL, and interactive paths when applicable).
- Reinstall local binary after changes:

```bash
sh ./install.sh
```

- Validate behavior in a real resume project directory.
- Update docs in this README when command behavior changes.

Project layout after init:

```text
.cv/state.env
.cv/auto.env
jobs/default/<name>.md
jobs/default/track.tsv
jobs/default/posts.json
tailored/
```

Resume versions are stored at:

```text
jobs/<job>/<name>.md
```

## Commands

```text
cv init [name]
cv install [target]
cv current
cv jobs [job] [name]
cv title <new title>
cv section [list|show|set|add|edit] ...
cv skills [list|add|rm|manage] ...
cv exp [list|add|rm|manage] ...
cv tags [text|url]
cv say <question>
cv fit <text|url>
cv tailor [text|url]
cv track [item] [status]
cv posts [list|all|filtered|show <index>]
cv auto [status|enable|disable]
cv ats [senior]
cv ci telegram [setup|status|send] [message]
cv help
```

## Integrations

See [docs/integrations.md](docs/integrations.md) for setup and script usage of Telegram integration.

See [docs/automation.md](docs/automation.md) for automated seek/filter/analyze/grade/store/apply/track/notify flow.

## Skills Management

```bash
cv skills
cv skills add "TypeScript"
cv skills rm "Skill 1"
cv skills manage
```

## Work Experience Management

List experience summaries, total years, gap months, and title relevancy:

```bash
cv exp
```

Add entry format:

```bash
cv exp add "Company|Role|YYYY-MM|YYYY-MM"
cv exp add "Company|Role|YYYY-MM|Present"
```

Accepted parser formats:

```text
### Company | Title | YYYY-MM to YYYY-MM

### Company
Title (or **Title** or Position: Title)
YYYY-MM to YYYY-MM
- Description bullets...
```

## Tailor Workflow

```bash
cv tailor
cv tailor https://example.com/jobs/frontend-engineer
cv tailor "Senior frontend role with React TypeScript"
```

Interactive prompts:

1. Company (only for `cv tailor` and `cv tailor "..."`)
2. Job title (only for `cv tailor` and `cv tailor "..."`)
3. Job description (only when no text/url argument is provided; paste, then Ctrl-D)

For URL input, `cv tailor <url>` fetches and truncates posting text, does not prompt for company/title, and asks AI to keep the job title exactly as written in the source text.

`cv tailor` also uses external ATS parser fields as validation hints for AI tailoring.

Output:

```text
tailored/<company>/<title>/<name>.md
tailored/<company>/<title>/<name>.docx
```

For URL input, output path uses a safe source bucket:

```text
tailored/from-url/<source-ref>/<name>.md
tailored/from-url/<source-ref>/<name>.docx
```

Requires:

- `copilot` CLI for AI tailoring.
- `pandoc` for `.docx` export.

## AI Q&A

```bash
cv say "Why are you relevant candidate for this role?"
```

Loads context from markdown files in current project.

## Tags Check

```bash
cv tags
cv tags "Senior frontend engineer with React, TypeScript, GraphQL"
cv tags https://example.com/jobs/frontend-engineer
```

Prints meaningful resume tags, total count, and whether total fits recommended 25-35 range.
With optional text or URL, also prints job tags and resume coverage of job tags.

## Job Fit Check

```bash
cv fit "Senior Frontend role with React and TypeScript"
cv fit https://example.com/jobs/frontend-engineer
```

Behavior:

- For text input: uses provided text as job description.
- For URL input: fetches page and extracts primary readable content, including JSON-LD/script-embedded descriptions used by JS-heavy job pages.
- Runs non-AI keyword overlap precheck and AI fit review.

## Application Tracking

```bash
cv track "Company Frontend"
cv track "Company Frontend" i2
cv track "Company Frontend" status
cv track
```

Status aliases:

- `applied` / `a`
- `interview` / `i` / `int` / `i2` / `int2`
- `rejected` / `r`
- `offer` / `o`
- `ghosted` / `g`

Ghosted status auto-applies after 30 days for open applications.

Storage location is job-local:

```text
jobs/<job>/track.tsv
```

## Parsed Posts

`cv auto enable` stores parsed and graded post records in:

```text
jobs/<job>/posts.json
```

View them with:

```bash
cv posts
cv posts all
cv posts show 1
```

## Automation

```bash
cv auto status
cv auto enable
cv auto disable
```

`cv auto enable` runs one automation cycle using `.cv/auto.env` settings:

- seek job links from `AUTO_SEARCH_URLS`
- parse and fit-score each post
- grade and store to `jobs/<job>/posts.json`
- optionally auto-apply with Playwright (`AUTO_APPLY=1`)
- track successful applies in `jobs/<job>/track.tsv`
- optionally notify via Telegram (`AUTO_NOTIFY=1`)

Full setup and config reference: [docs/automation.md](docs/automation.md).

## ATS Check

```bash
cv ats
cv ats senior
```

Steps:

1. External ATS parse source: `pyresparser` (if installed).
2. Automatic external fallback: `spaCy NER` parser when `pyresparser` is unavailable or broken.
3. Structure + parser field score.
4. AI score and actionable advice via `copilot`.

If external ATS parser is not installed, `cv ats` attempts auto-setup first and prints detailed setup errors if it still fails.

`cv ats senior` emulates a practical senior-profile ATS filter with pass/fail checks (experience years, title signal, leadership signal, skill overlap, multi-company history).

External ATS parser fields are also reused by:

- `cv tags` for tag enrichment.
- `cv exp` for extraction validation hints.
- `cv fit` for resume keyword enrichment.
- `cv tailor` for ATS-guided prompt context.
