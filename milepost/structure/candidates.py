"""Module candidates proposed from directories under `structure.roots` (SPEC section 9.1)."""

import re
from dataclasses import dataclass
from pathlib import Path

from milepost.config import Structure
from milepost.core.glob import expand_sources

EXTENSIONS_BY_LANGUAGE = {
    "python": [".py"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx"],
}


@dataclass
class Candidate:
    """A proposed module. Never active: only a person (or an explicit flag) declares modules."""

    id: str
    path: str
    sources: list[str]
    active: bool = False


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-_")
    return slug or "module"


def _unique_id(child: str, root_rel: str, taken: set[str]) -> str:
    candidate = _slug(child)
    if candidate not in taken:
        return candidate
    candidate = _slug(f"{root_rel}-{child}")
    suffix = 2
    unique = candidate
    while unique in taken:
        unique = f"{candidate}-{suffix}"
        suffix += 1
    return unique


def scan_candidates(root: Path, structure: Structure) -> list[Candidate]:
    patterns = [
        ext for language in structure.languages for ext in EXTENSIONS_BY_LANGUAGE.get(language, [])
    ]
    candidates: list[Candidate] = []
    taken: set[str] = set()
    for root_rel in structure.roots:
        base = root / root_rel
        if not base.is_dir():
            continue
        for child in sorted(path for path in base.iterdir() if path.is_dir()):
            rel = f"{root_rel}/{child.name}"
            sources = [
                glob
                for glob in (f"{rel}/**/*{ext}" for ext in patterns)
                if expand_sources(root, [glob], structure.ignore)
            ]
            if not sources:
                continue
            candidate_id = _unique_id(child.name, root_rel, taken)
            taken.add(candidate_id)
            candidates.append(Candidate(id=candidate_id, path=rel, sources=sources))
    return candidates
