"""Import edges for Python files, using the stdlib `ast` module."""

import ast
from pathlib import Path, PurePosixPath
from typing import Literal

from milepost.structure.base import Edge, ScanResult


def _module_file(root: Path, base: str, dotted: str) -> str | None:
    """Repo-relative file for a dotted module name below `base`, or None."""
    parts = [part for part in (*PurePosixPath(base).parts, *dotted.split(".")) if part]
    stem = "/".join(parts)
    candidates = [f"{stem}.py", f"{stem}/__init__.py"] if dotted else [f"{stem}/__init__.py"]
    for candidate in candidates:
        if (root / candidate).is_file():
            return candidate.lstrip("/")
    return None


def _absolute_bases(source: str) -> list[str]:
    """Directories an absolute import may be rooted at: the repo root, then each ancestor dir."""
    parents = PurePosixPath(source).parent.parts
    return ["", *("/".join(parents[: depth + 1]) for depth in range(len(parents)))]


def _resolve_absolute(root: Path, source: str, dotted: str) -> str | None:
    for base in _absolute_bases(source):
        found = _module_file(root, base, dotted)
        if found:
            return found
    return None


def _edges_for_import(root: Path, source: str, node: ast.Import) -> list[Edge]:
    edges = []
    for alias in node.names:
        found = _resolve_absolute(root, source, alias.name)
        edges.append(
            Edge(source, found, "internal") if found else Edge(source, alias.name, "external")
        )
    return edges


def _edges_for_import_from(root: Path, source: str, node: ast.ImportFrom) -> list[Edge]:
    module = node.module or ""
    if node.level:
        package = PurePosixPath(source).parent.parts
        base = "/".join(package[: len(package) - (node.level - 1)])

        def resolve(dotted: str) -> str | None:
            return _module_file(root, base, dotted)

        raw = "." * node.level + module
    else:

        def resolve(dotted: str) -> str | None:
            return _resolve_absolute(root, source, dotted)

        raw = module

    module_file = resolve(module)
    edges: list[Edge] = []
    for alias in node.names:
        submodule = resolve(f"{module}.{alias.name}" if module else alias.name)
        if alias.name != "*" and submodule:
            edges.append(Edge(source, submodule, "internal"))
        elif module_file:
            edges.append(Edge(source, module_file, "internal"))
        else:
            kind: Literal["unresolved", "external"] = "unresolved" if node.level else "external"
            edges.append(Edge(source, raw, kind))
    return edges


def scan_python(root: Path, paths: list[str]) -> ScanResult:
    result = ScanResult()
    for source in paths:
        try:
            tree = ast.parse((root / source).read_text(encoding="utf-8"), filename=source)
        except (SyntaxError, UnicodeDecodeError, OSError) as error:
            result.errors.append(f"{source}: {error}")
            continue
        found: list[Edge] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.extend(_edges_for_import(root, source, node))
            elif isinstance(node, ast.ImportFrom):
                found.extend(_edges_for_import_from(root, source, node))
        result.edges.extend(dict.fromkeys(found))
    return result
