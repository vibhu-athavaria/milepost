"""`milepost doctor`: report what the environment must provide (SPEC section 8)."""

import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from milepost.config import load_config
from milepost.embeddings import semantic_search_available
from milepost.errors import MilepostError
from milepost.services.coverage import CONFIG_NAME
from milepost.services.hooks import outdated_hooks

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


def _fts5_available() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        conn.close()
    except sqlite3.Error:
        return False
    return True


def _config_error(root: Path) -> str:
    """The reason milepost.toml is unusable; empty when it is absent or valid."""
    if not (root / CONFIG_NAME).is_file():
        return ""
    try:
        load_config(root / CONFIG_NAME)
    except MilepostError as error:
        return str(error)
    return ""


def run_doctor(root: Path) -> DoctorReport:
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
    config_error = _config_error(root)
    if config_error:
        checks.append(Check(CONFIG_NAME, "fail", config_error))
    if not semantic_search_available():
        checks.append(
            Check(
                "search",
                "warn",
                "meaning-based search is off (keyword search only); "
                "pip install 'milepost[search]' to turn it on",
            )
        )
    outdated = outdated_hooks(root) if shutil.which("git") else []
    if outdated:
        checks.append(
            Check(
                "git-hooks",
                "warn",
                f"{', '.join(outdated)} written by an older milepost; run `milepost hooks install`",
            )
        )
    return DoctorReport(checks)
