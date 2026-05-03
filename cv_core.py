#!/usr/bin/env python3
from __future__ import annotations

import sys

from cvapp.app import CVError, main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CVError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
