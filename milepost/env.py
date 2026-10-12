"""Environment variables for drafting: the shell first, then a .env file at the repo root."""

import os
import subprocess
from collections.abc import MutableMapping
from pathlib import Path

from dotenv import dotenv_values

DOTENV_NAME = ".env"


def load_env(root: Path, environ: MutableMapping[str, str] | None = None) -> None:
    """Add variables from <root>/.env to `environ` (default os.environ); a set one is kept."""
    target = os.environ if environ is None else environ
    path = root / DOTENV_NAME
    if not path.is_file():
        return
    for key, value in dotenv_values(path).items():
        if value and not target.get(key):
            target[key] = value


def dotenv_is_ignored(root: Path) -> bool:
    """True when there is no .env file, or git ignores it. False means it could be committed."""
    if not (root / DOTENV_NAME).is_file():
        return True
    done = subprocess.run(
        ["git", "check-ignore", "-q", DOTENV_NAME], cwd=root, capture_output=True, check=False
    )
    return done.returncode == 0
