from __future__ import annotations

from typing import Callable

from .config import CV_VERSION
from .errors import die
from .features.ats.api import cmd_ats
from .features.auto.api import cmd_auto
from .features.fit.api import cmd_fit
from .features.posts.api import cmd_posts
from .features.resume.api import cmd_current, cmd_exp, cmd_init, cmd_jobs, cmd_section, cmd_skills, cmd_tags, cmd_title
from .features.say.api import cmd_say
from .features.tailor.api import cmd_tailor
from .features.track.api import cmd_track
from .internal.telegram import cmd_ci
from .strings import HELP_TEXT, UNKNOWN_COMMAND_TEMPLATE

CommandHandler = Callable[[list[str]], int]


def cmd_help(args: list[str] | None = None) -> int:
    del args
    print(HELP_TEXT)
    return 0


def cmd_version(args: list[str]) -> int:
    del args
    print(f"cv {CV_VERSION}")
    return 0


COMMANDS: dict[str, CommandHandler] = {
    "init": cmd_init,
    "current": cmd_current,
    "jobs": cmd_jobs,
    "title": cmd_title,
    "section": cmd_section,
    "skills": cmd_skills,
    "exp": cmd_exp,
    "tags": cmd_tags,
    "say": cmd_say,
    "fit": cmd_fit,
    "tailor": cmd_tailor,
    "track": cmd_track,
    "posts": cmd_posts,
    "auto": cmd_auto,
    "ats": cmd_ats,
    "ci": cmd_ci,
}


def dispatch(cmd: str, args: list[str]) -> int:
    if cmd in {"help", "-h", "--help"}:
        return cmd_help([])
    if cmd in {"version", "-v", "--version"}:
        return cmd_version(args)

    handler = COMMANDS.get(cmd)
    if handler is None:
        die(UNKNOWN_COMMAND_TEMPLATE.format(cmd=cmd))
        return 1

    return handler(args)
