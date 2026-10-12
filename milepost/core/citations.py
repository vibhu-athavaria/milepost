"""Paths that Invariants and Gotchas bullets cite in backticks (SPEC sections 4.2 and 8.3)."""

import re
from dataclasses import dataclass, field

from milepost.core.notes import section

CITING_SECTIONS = ("Invariants", "Gotchas")
_BACKTICK = re.compile(r"`([^`\n]+)`")
_SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs")


@dataclass
class Bullet:
    section: str
    text: str
    paths: list[str] = field(default_factory=list)


def _cited_path(span: str) -> str | None:
    candidate = span.split("::", 1)[0].strip().removesuffix("()")
    if not candidate or " " in candidate or candidate.startswith("/"):
        return None
    if any(char in candidate for char in "{}*?"):
        return None
    if "/" in candidate or candidate.endswith(_SOURCE_SUFFIXES):
        return candidate
    return None


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
