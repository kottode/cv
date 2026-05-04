from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from ..errors import CVError

SCHEDULE_MARKER = "# cv-auto-hourly"


def _hourly_cron_line() -> str:
    cv_bin = Path.home() / ".local" / "bin" / "cv"
    return (
        "0 * * * * "
        "mkdir -p \"$HOME/.local/share/cv\" && "
        f"cd \"$HOME/Resume\" && \"{cv_bin}\" auto enable "
        ">> \"$HOME/.local/share/cv/auto-hourly.log\" 2>&1 "
        f"{SCHEDULE_MARKER}"
    )


def _read_crontab_lines() -> list[str]:
    proc = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
    if proc.returncode not in {0, 1}:
        raise CVError(f"Failed to read crontab: {(proc.stderr or proc.stdout).strip()}")
    if proc.returncode == 1:
        return []
    return [line.rstrip("\n") for line in proc.stdout.splitlines()]


def _write_crontab_lines(lines: list[str]) -> None:
    payload = "\n".join(lines).strip()
    if payload:
        payload += "\n"
    proc = subprocess.run(["crontab", "-"], input=payload, text=True, capture_output=True)
    if proc.returncode != 0:
        raise CVError(f"Failed to write crontab: {(proc.stderr or proc.stdout).strip()}")


def has_hourly_auto_schedule() -> bool:
    return any(SCHEDULE_MARKER in line for line in _read_crontab_lines())


def next_hourly_auto_run(reference: datetime | None = None) -> str:
    now = reference.astimezone() if reference is not None else datetime.now().astimezone()
    next_run = now.replace(minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(hours=1)
    return next_run.strftime("%Y-%m-%d %H:%M %Z")


def enable_hourly_auto_schedule() -> str:
    lines = [line for line in _read_crontab_lines() if SCHEDULE_MARKER not in line]
    cron_line = _hourly_cron_line()
    lines.append(cron_line)
    _write_crontab_lines(lines)
    return cron_line


def disable_hourly_auto_schedule() -> bool:
    lines = _read_crontab_lines()
    kept = [line for line in lines if SCHEDULE_MARKER not in line]
    changed = len(kept) != len(lines)
    if changed:
        _write_crontab_lines(kept)
    return changed
