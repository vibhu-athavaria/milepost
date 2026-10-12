"""`milepost outline`: symbols of one file with line ranges, computed now (SPEC section 8.3)."""

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from milepost.errors import NotFoundError, UsageError
from milepost.structure.outline import SUPPORTED_EXTENSIONS, Symbol, parse_symbols

MAX_SYMBOLS = 200


@dataclass
class OutlineResult:
    path: str
    line_count: int
    symbols: list[Symbol] = field(default_factory=list)
    truncated: bool = False


def resolve_repo_file(root: Path, path: str) -> tuple[str, Path]:
    """(repo-relative POSIX path, absolute path) of a file that must be inside the repo."""
    absolute = (root / path).resolve()
    try:
        relative = absolute.relative_to(root.resolve())
    except ValueError as error:
        raise UsageError(f"{path} is outside the repository") from error
    if not absolute.is_file():
        raise NotFoundError(f"{relative.as_posix()} is not a file in this repository")
    return relative.as_posix(), absolute


def outline_file(root: Path, path: str) -> OutlineResult:
    relative, absolute = resolve_repo_file(root, path)
    data = absolute.read_bytes()
    line_count = len(data.decode("utf-8", errors="replace").splitlines())
    extension = PurePosixPath(relative).suffix
    if extension not in SUPPORTED_EXTENSIONS:
        raise UsageError(
            f"cannot outline {relative}: unsupported file type '{extension}' "
            f"({line_count} lines; read it directly)"
        )
    try:
        symbols = parse_symbols(relative, data)
    except SyntaxError as error:
        raise UsageError(
            f"cannot outline {relative}: it does not parse ({error.msg}, line {error.lineno}); "
            f"{line_count} lines, read it directly"
        ) from error
    truncated = len(symbols) > MAX_SYMBOLS
    return OutlineResult(relative, line_count, symbols[:MAX_SYMBOLS], truncated)
