from __future__ import annotations

import sys

from .commands import dispatch
from .errors import CVError


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        return dispatch("help", [])

    cmd = argv[0]
    args = argv[1:]
    return dispatch(cmd, args)
