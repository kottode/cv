from __future__ import annotations

import sys


class CVError(Exception):
    pass


def die(message: str) -> None:
    raise CVError(message)


def warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)
