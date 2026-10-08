"""Types shared by the structure scanners (SPEC section 15)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class Edge:
    """An import from `source` (repo-relative path) to `target`.

    `internal`: target is a repo-relative path of a file in the repository.
    `external`: target is a module name outside the repository.
    `unresolved`: target is the raw specifier; the scanner could not follow it.
    """

    source: str
    target: str
    kind: Literal["internal", "external", "unresolved"]


@dataclass
class ScanResult:
    edges: list[Edge] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class Scanner(Protocol):
    def __call__(self, root: Path, paths: list[str]) -> ScanResult: ...
