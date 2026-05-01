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

Project layout after init:

```text
.cv/state.env
.cv/track.tsv
jobs/default/<name>.md
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
cv tailor
cv track [item] [status]
cv ats
cv help
```

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

Expected markdown line format for parser:

```text
### Company | Title | YYYY-MM to YYYY-MM
```

## Tailor Workflow

```bash
cv tailor
```

Interactive prompts:

1. Company
2. Job title
3. Job description (paste, then Ctrl-D)

Output:

```text
tailored/<company>/<title>/<name>.md
tailored/<company>/<title>/<name>.docx
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

## ATS Check

```bash
cv ats
```

Steps:

1. External ATS parse source: `pyresparser` (if installed).
2. Automatic external fallback: `spaCy NER` parser when `pyresparser` is unavailable or broken.
3. Structure + parser field score.
4. AI score and actionable advice via `copilot`.

If external ATS parser is not installed, `cv ats` attempts auto-setup first and prints detailed setup errors if it still fails.

## Prompt Label

`cv init` installs a shell prompt hook in `~/.bashrc`.

Behavior:

- Shows a name-based label with icon (for example `[󰈙 john-bang-gang]`) when you are inside a CV project tree.
- Hides automatically when you leave the project tree.
- Updates automatically when you switch resumes/jobs.
