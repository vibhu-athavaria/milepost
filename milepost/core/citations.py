"""Paths that Invariants and Gotchas bullets cite in backticks (SPEC sections 4.2 and 8.3)."""

import re
from dataclasses import dataclass, field

from milepost.core.notes import section

CITING_SECTIONS = ("Invariants", "Gotchas")
CHECKED_SECTIONS = ("Entry points", "File map", *CITING_SECTIONS)
_BACKTICK = re.compile(r"`([^`\n]+)`")
_SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs")


@dataclass
class Bullet:
    section: str
    text: str
    paths: list[str] = field(default_factory=list)


def _split_citation(span: str) -> tuple[str, str] | None:
    """(path, symbol) for a backtick span that cites a file, else None. Symbol may be empty."""
    path = _cited_path(span)
    if path is None:
        return None
    _, _, symbol = span.partition("::")
    return path, symbol.strip().removesuffix("()")


_LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")
_FILE_LIKE = re.compile(r"\.[A-Za-z0-9]{1,6}$")
# A bare `name.ext` is only a file if ext is a known file type; otherwise `Class.method` would be.
_KNOWN_EXTENSIONS = (
    *_SOURCE_SUFFIXES,
    ".md", ".json", ".toml", ".yml", ".yaml", ".sql", ".css", ".scss", ".html", ".sh", ".txt",
    ".cfg", ".ini", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".c", ".h", ".cpp", ".cs",
    ".swift", ".vue", ".svelte", ".lock",
)  # fmt: skip


def _cited_path(span: str) -> str | None:
    """The repo path a backtick span cites, or None. A path must look like a file (end in an
    extension) or a directory (end in "/"); routes such as `api/users` and phrases such as
    `and/or` or `text/plain` are not paths. A leading "./" and a ":42" line suffix are dropped."""
    candidate = span.split("::", 1)[0].strip().removesuffix("()")
    candidate = _LINE_SUFFIX.sub("", candidate).removeprefix("./")
    if not candidate or " " in candidate or candidate.startswith("/") or "://" in candidate:
        return None
    if any(char in candidate for char in "{}*?"):
        return None
    if candidate.endswith("/"):
        return candidate
    if "/" in candidate:
        return candidate if _FILE_LIKE.search(candidate) else None
    return candidate if candidate.endswith(_KNOWN_EXTENSIONS) else None


def path_matches(candidate: str, cited: str) -> bool:
    """A cited path matches a repo path when equal, or when it is a suffix after a "/"."""
    return candidate == cited or candidate.endswith("/" + cited)


def _bullets_of(text: str) -> list[str]:
    bullets: list[str] = []
    for line in text.splitlines():
        if re.match(r"\s*[-*]\s+", line):
            bullets.append(re.sub(r"^\s*[-*]\s+", "", line).strip())
        elif bullets and line.strip():
            bullets[-1] += " " + line.strip()
    return bullets


def cited_bullets(body: str) -> list[Bullet]:
    """Every Invariants and Gotchas bullet that cites at least one path in backticks."""
    found: list[Bullet] = []
    for name in CITING_SECTIONS:
        text = section(body, name)
        if text is None:
            continue
        for bullet in _bullets_of(text):
            paths = [p for span in _BACKTICK.findall(bullet) if (p := _cited_path(span))]
            if paths:
                found.append(Bullet(name, bullet, list(dict.fromkeys(paths))))
    return found


def citing_changed(body: str, candidates: set[str], changed: set[str]) -> list[tuple[Bullet, str]]:
    """Bullets whose cited path is one of the `changed` files.

    A citation matches a candidate file when it equals the path or is a suffix after a "/",
    and exactly one candidate has that suffix; an ambiguous citation is skipped, not guessed."""
    found = []
    for bullet in cited_bullets(body):
        for cited in bullet.paths:
            matches = [p for p in candidates if path_matches(p, cited)]
            if len(matches) == 1 and matches[0] in changed:
                found.append((bullet, matches[0]))
    return found


def all_citations(body: str) -> list[tuple[str, str]]:
    """Every (path, symbol) cited in backticks in the sections that make factual claims."""
    found: list[tuple[str, str]] = []
    for name in CHECKED_SECTIONS:
        text = section(body, name)
        if text is None:
            continue
        for span in _BACKTICK.findall(text):
            citation = _split_citation(span)
            if citation is not None:
                found.append(citation)
    return list(dict.fromkeys(found))
