"""`milepost impact`: who imports a file and which tests likely cover it (SPEC section 8.3).

A static import graph: dynamic imports, string-based plugin loading and framework wiring are not
seen.
"""

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from milepost.config import Config
from milepost.core.glob import expand_sources, matches_any
from milepost.errors import UsageError
from milepost.services.gitinfo import repo_files
from milepost.services.outline import resolve_repo_file
from milepost.structure.candidates import EXTENSIONS_BY_LANGUAGE
from milepost.structure.python_scanner import scan_python
from milepost.structure.tree_sitter_scanner import scan_typescript

MAX_ITEMS = 50
_ALWAYS_IGNORE = ["**/.git/**", "**/venv/**", "**/site-packages/**"]
_TEST_DIRS = {"tests", "test", "__tests__"}
_TEST_NAMES = ["test_*.py", "*_test.py", "*.test.*", "*.spec.*"]


@dataclass
class TestRef:
    __test__ = False  # not a pytest class

    path: str
    via: str


@dataclass
class ModuleRef:
    id: str
    verify: list[str] = field(default_factory=list)


@dataclass
class ImpactResult:
    path: str
    importers: list[str] = field(default_factory=list)
    tests: list[TestRef] = field(default_factory=list)
    modules: list[ModuleRef] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    truncated: bool = False
    caveat: str = "static import graph: dynamic imports and framework wiring are not seen"


def is_test_path(path: str) -> bool:
    pure = PurePosixPath(path)
    return bool(_TEST_DIRS & set(pure.parts[:-1])) or any(
        fnmatch.fnmatch(pure.name, pattern) for pattern in _TEST_NAMES
    )


def _stem(path: str) -> str:
    pure = PurePosixPath(path)
    return pure.parent.name if pure.stem in ("__init__", "index") else pure.stem


def _source_files(root: Path, config: Config) -> list[str]:
    """Source files in the configured languages. Uses git's file list when there is one, so
    ignored directories (virtualenvs, build output, agent worktrees) are never read."""
    extensions = tuple(
        ext for lang in config.structure.languages for ext in EXTENSIONS_BY_LANGUAGE.get(lang, [])
    )
    ignore = [*config.structure.ignore, *_ALWAYS_IGNORE]
    try:
        names = repo_files(root)
    except UsageError:
        return expand_sources(root, [f"**/*{ext}" for ext in extensions], ignore)
    return [n for n in names if n.endswith(extensions) and not matches_any(n, ignore)]


def _importers(root: Path, files: list[str], target: str) -> list[str]:
    stem = _stem(target)
    candidates = []
    for path in files:
        if path == target:
            continue
        try:
            text = (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if stem in text:
            candidates.append(path)
    python = [p for p in candidates if p.endswith(".py")]
    others = [p for p in candidates if not p.endswith(".py")]
    edges = [*scan_python(root, python).edges, *scan_typescript(root, others).edges]
    return sorted({e.source for e in edges if e.kind == "internal" and e.target == target})


def _covering_notes(root: Path, config: Config, path: str, module_ids: list[str]) -> list[str]:
    kb = root / config.project.kb_dir
    notes = [f"module/{m}" for m in module_ids if (kb / "modules" / f"{m}.md").is_file()]
    if (kb / "files" / f"{path}.md").is_file():
        notes.append(f"file/{path}")
    return notes


def file_impact(root: Path, config: Config, path: str) -> ImpactResult:
    relative, _ = resolve_repo_file(root, path)
    files = _source_files(root, config)
    importers = _importers(root, files, relative)
    stem = _stem(relative)
    tests = [TestRef(p, "import") for p in importers if is_test_path(p)]
    imported_tests = {t.path for t in tests}
    tests += [
        TestRef(p, "name")
        for p in files
        if is_test_path(p) and p not in imported_tests and p != relative and stem in p
    ]
    modules = [
        ModuleRef(module_id, module.verify)
        for module_id, module in sorted(config.modules.items())
        if matches_any(relative, module.sources)
    ]
    result = ImpactResult(
        path=relative,
        importers=importers,
        tests=tests,
        modules=modules,
        notes=_covering_notes(root, config, relative, [m.id for m in modules]),
    )
    if len(result.importers) > MAX_ITEMS or len(result.tests) > MAX_ITEMS:
        result.truncated = True
        result.importers = result.importers[:MAX_ITEMS]
        result.tests = result.tests[:MAX_ITEMS]
    return result
