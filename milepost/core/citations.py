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


def citing_changed(body: str, candidates: set[str], changed: set[str]) -> list[tuple[Bullet, str]]:
    """Bullets whose cited path is one of the `changed` files.

    A citation matches a candidate file when it equals the path or is a suffix after a "/",
    and exactly one candidate has that suffix; an ambiguous citation is skipped, not guessed."""
    found = []
    for bullet in cited_bullets(body):
        for cited in bullet.paths:
            matches = [p for p in candidates if p == cited or p.endswith("/" + cited)]
            if len(matches) == 1 and matches[0] in changed:
                found.append((bullet, matches[0]))
    return found
