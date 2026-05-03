# Automated Job Application

`cv auto [status|enable|disable]` runs a self-hosted automation cycle for the current job profile.

## What It Does

When you run `cv auto enable`, the CLI uses internal functions (not shelling out to other `cv` commands) to:

1. Seek candidate post URLs from configured seed URLs.
2. Fetch and parse post text.
3. Analyze and fit-score each post against the current resume.
4. Grade posts (`A/B/C/D`) and filter using score and keyword rules.
5. Store parsed records in the job-local post store.
6. Auto-apply using Playwright when enabled.
7. Track successful applies in the job-local tracking file.
8. Send a run summary to Telegram when enabled and configured.

## Commands

```bash
cv auto status
cv auto enable
cv auto disable

cv posts
cv posts all
cv posts filtered
cv posts show 1
```

## Files

Automation state is project-local and job-local:

- `.cv/auto.env`
- `jobs/<job>/posts.json`
- `jobs/<job>/track.tsv`

## Configure `.cv/auto.env`

`cv auto status` creates `.cv/auto.env` if missing.

Example:

```env
AUTO_ENABLED="0"
AUTO_SEARCH_URLS="https://boards.greenhouse.io/example,https://jobs.lever.co/example"
AUTO_INCLUDE_KEYWORDS="frontend,react,typescript"
AUTO_EXCLUDE_KEYWORDS="intern,principal"
AUTO_MIN_SCORE="60"
AUTO_MAX_POSTS="12"
AUTO_MAX_LINKS_PER_SEED="25"
AUTO_APPLY="1"
AUTO_NOTIFY="1"
AUTO_LAST_RUN_AT=""
AUTO_LAST_SEEKED="0"
AUTO_LAST_PARSED="0"
AUTO_LAST_FILTERED="0"
AUTO_LAST_STORED="0"
AUTO_LAST_APPLIED="0"
AUTO_LAST_ERROR=""
```

Field meanings:

- `AUTO_SEARCH_URLS`: comma-separated seed URLs to crawl for job links.
- `AUTO_INCLUDE_KEYWORDS`: optional. At least one must appear in post text.
- `AUTO_EXCLUDE_KEYWORDS`: optional. Any match filters a post out.
- `AUTO_MIN_SCORE`: minimum fit score for accepted posts.
- `AUTO_MAX_POSTS`: max posts parsed per run.
- `AUTO_MAX_LINKS_PER_SEED`: crawl budget per seed URL.
- `AUTO_APPLY`: `1` enables Playwright auto-apply attempts.
- `AUTO_NOTIFY`: `1` sends run summary to Telegram if configured.

You can also override seed URLs for one run via environment variable:

```bash
CV_AUTO_SEARCH_URLS="https://boards.greenhouse.io/example" cv auto enable
```

## Post Store and Viewer

Each parsed post record includes:

- URL, inferred company/title
- status (`accepted` or `filtered`) and filter reason
- fit score and grade
- matched and missing tags
- apply status and detail
- optional tracking item for successful apply
- timestamps

Inspect details:

```bash
cv posts show <index>
```

## Auto-Apply (Playwright)

Auto-apply is best-effort. The current implementation attempts to click/navigate through common apply controls.

If Playwright is not installed, posts remain stored and graded, and apply status becomes `manual-required`.

Install Playwright:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

## Telegram Notifications

Set up Telegram first:

```bash
cv ci telegram
```

Then keep `AUTO_NOTIFY="1"` in `.cv/auto.env`.

If Telegram is not configured, automation still runs and skips notification.

## Suggested Scheduling

`cv auto enable` performs one cycle immediately and keeps automation marked enabled in config.

For recurring runs, schedule the command externally (cron/systemd timer/GitHub Actions runner on your machine):

```bash
cd /path/to/project && cv auto enable
```

## Notes

- URL crawling and apply interactions depend on each site layout and anti-bot controls.
- Keep your include/exclude keywords strict to reduce low-fit submissions.
- Review with `cv posts` regularly, especially when enabling auto-apply.
