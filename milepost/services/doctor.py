"""`milepost doctor`: report what the environment must provide (SPEC section 8)."""

import shutil
import sqlite3
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from milepost.env import DOTENV_NAME, dotenv_is_ignored

MODEL_VAR = "MILEPOST_MODEL"
Status = Literal["ok", "warn", "fail"]


@dataclass
class Check:
    name: str
    status: Status
    detail: str


@dataclass
class DoctorReport:
    checks: list[Check]

    @property
    def exit_code(self) -> int:
        return 3 if any(check.status == "fail" for check in self.checks) else 0


def litellm_missing_keys(model: str) -> list[str]:
    import litellm

    result = litellm.validate_environment(model)
    return [str(key) for key in result.get("missing_keys", [])]


def _fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        conn.close()
    except sqlite3.Error:
        return False
    return True


def run_doctor(
    root: Path,
    environ: Mapping[str, str],
    missing_keys: Callable[[str], list[str]] = litellm_missing_keys,
) -> DoctorReport:
    """Environment variables must already include anything loaded from .env (see env.load_env)."""
    checks = [
        Check("python", "ok", sys.version.split()[0]),
        Check(
            "git",
            "ok" if shutil.which("git") else "fail",
            "found" if shutil.which("git") else "git is not on PATH",
        ),
        Check(
            "sqlite-fts5",
            "ok" if _fts5_available() else "fail",
            "available" if _fts5_available() else "this SQLite build has no FTS5",
        ),
    ]
    model = environ.get(MODEL_VAR, "")
    if not model:
        checks.append(
            Check(MODEL_VAR, "fail", f"{MODEL_VAR} is not set (set it in the shell or in .env)")
        )
    else:
        checks.append(Check(MODEL_VAR, "ok", model))
        missing = missing_keys(model)
        if missing:
            checks.append(
                Check(
                    "provider-key",
                    "fail",
                    f"{', '.join(missing)} is not set (set it in the shell or in .env)",
                )
            )
        else:
            checks.append(Check("provider-key", "ok", "present"))
    if not dotenv_is_ignored(root):
        checks.append(
            Check(
                DOTENV_NAME,
                "warn",
                f"{DOTENV_NAME} exists but git does not ignore it; add it to .gitignore "
                "so keys are not committed",
            )
        )
    return DoctorReport(checks)
