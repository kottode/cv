from __future__ import annotations

import shutil
import subprocess

from ..config import DEFAULT_MODEL
from ..errors import die


def run(prompt: str, capture: bool = False) -> str:
    if shutil.which("copilot") is None:
        die("copilot CLI not found")

    args = ["copilot", "--model", DEFAULT_MODEL, "--allow-all-paths", "-p", prompt, "-s"]
    if capture:
        proc = subprocess.run(args, text=True, capture_output=True)
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, args, output=proc.stdout, stderr=proc.stderr)
        return proc.stdout

    proc = subprocess.run(args)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args)
    return ""
