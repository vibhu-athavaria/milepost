"""Import edges for TypeScript and JavaScript files, using tree-sitter."""

import posixpath
from pathlib import Path, PurePosixPath

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from milepost.structure.base import Edge, ScanResult

_JAVASCRIPT = Language(tree_sitter_javascript.language())
_LANGUAGES = {
    ".ts": Language(tree_sitter_typescript.language_typescript()),
    ".tsx": Language(tree_sitter_typescript.language_tsx()),
    ".js": _JAVASCRIPT,
    ".jsx": _JAVASCRIPT,
    ".mjs": _JAVASCRIPT,
}
_EXTENSIONS = list(_LANGUAGES)


def _string_value(node: Node) -> str:
    text = (node.text or b"").decode("utf-8")
    return text[1:-1] if node.type == "string" and len(text) >= 2 else text


def _specifiers(node: Node) -> list[tuple[str, bool]]:
    """(specifier, is_dynamic) for every import-like construct in the tree."""
    found: list[tuple[str, bool]] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in ("import_statement", "export_statement"):
            source = current.child_by_field_name("source")
            if source is not None:
                found.append((_string_value(source), False))
        elif current.type == "call_expression":
            function = current.child_by_field_name("function")
            arguments = current.child_by_field_name("arguments")
            if function is not None and function.type == "import" and arguments is not None:
                first = arguments.named_children[0] if arguments.named_children else None
                if first is not None:
                    found.append((_string_value(first), True))
        stack.extend(reversed(current.children))
    return found


def _resolve_relative(root: Path, source: str, specifier: str) -> str | None:
    joined = posixpath.normpath(posixpath.join(PurePosixPath(source).parent.as_posix(), specifier))
    if joined.startswith(".."):
        return None
    stem = joined.rsplit(".", 1)[0] if joined.endswith((".js", ".jsx")) else joined
    candidates = [joined]
    candidates += [f"{joined}{ext}" for ext in _EXTENSIONS]
    candidates += [f"{joined}/index{ext}" for ext in _EXTENSIONS]
    candidates += [f"{stem}{ext}" for ext in (".ts", ".tsx")]
    for candidate in candidates:
        if (root / candidate).is_file():
            return candidate
    return None


def scan_typescript(root: Path, paths: list[str]) -> ScanResult:
    result = ScanResult()
    for source in paths:
        language = _LANGUAGES.get(PurePosixPath(source).suffix)
        if language is None:
            continue
        try:
            tree = Parser(language).parse((root / source).read_bytes())
        except OSError as error:
            result.errors.append(f"{source}: {error}")
            continue
        found: list[Edge] = []
        for specifier, dynamic in _specifiers(tree.root_node):
            if dynamic:
                found.append(Edge(source, specifier, "unresolved"))
            elif specifier.startswith("."):
                target = _resolve_relative(root, source, specifier)
                found.append(
                    Edge(source, target, "internal")
                    if target
                    else Edge(source, specifier, "unresolved")
                )
            else:
                found.append(Edge(source, specifier, "external"))
        result.edges.extend(dict.fromkeys(found))
    return result
