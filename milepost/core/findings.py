"""A single check result, shared by note validation and `milepost check`."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Finding:
    severity: Literal["failure", "warning"]
    code: str
    path: str
    message: str
    # What a waiver names: a note id, or "dir:<path>" for an uncovered directory.
    subject: str = ""
