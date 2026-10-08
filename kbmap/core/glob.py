"""Source set expansion (SPEC section 5, step 1)."""

from pathlib import Path

from wcmatch import glob

FLAGS = glob.GLOBSTAR | glob.DOTGLOB | glob.FOLLOW


def expand_sources(root: Path, sources: list[str], ignore: list[str]) -> list[str]:
    """Return sorted, de-duplicated repo-relative POSIX paths of regular files in the source set."""
    matched: set[str] = set()
    for pattern in sources:
        for found in glob.glob(pattern, root_dir=root, flags=FLAGS):
            relative = Path(found).as_posix()
            if (root / relative).is_file():
                matched.add(relative)
    if ignore:
        matched = {path for path in matched if not glob.globmatch(path, ignore, flags=FLAGS)}
    return sorted(matched)
