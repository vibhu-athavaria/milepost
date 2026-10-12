"""Symbols of one source file with line ranges, parsed at call time (SPEC section 8.3)."""

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

DOC_MAX = 120
PYTHON_EXTENSIONS = {".py"}
_JAVASCRIPT = Language(tree_sitter_javascript.language())
_TS_LANGUAGES = {
    ".ts": Language(tree_sitter_typescript.language_typescript()),
    ".tsx": Language(tree_sitter_typescript.language_tsx()),
    ".js": _JAVASCRIPT,
    ".jsx": _JAVASCRIPT,
    ".mjs": _JAVASCRIPT,
}
SUPPORTED_EXTENSIONS = PYTHON_EXTENSIONS | set(_TS_LANGUAGES)


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    signature: str
    doc: str
    start_line: int
    end_line: int


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0].strip() if text.strip() else ""


def _clip(text: str) -> str:
    return text if len(text) <= DOC_MAX else text[: DOC_MAX - 3].rstrip() + "..."


def _python_symbols(source: str) -> list[Symbol]:
    tree = ast.parse(source)
    lines = source.splitlines()
    symbols: list[Symbol] = []

    def header(node: ast.stmt) -> str:
        return lines[node.lineno - 1].strip()

    def start(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> int:
        return min([node.lineno, *(d.lineno for d in node.decorator_list)])

    def visit(body: list[ast.stmt], prefix: str, in_class: bool) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                symbols.append(
                    Symbol(
                        prefix + node.name,
                        "method" if in_class else "function",
                        header(node),
                        _clip(_first_line(ast.get_docstring(node) or "")),
                        start(node),
                        node.end_lineno or node.lineno,
                    )
                )
            elif isinstance(node, ast.ClassDef):
                symbols.append(
                    Symbol(
                        prefix + node.name,
                        "class",
                        header(node),
                        _clip(_first_line(ast.get_docstring(node) or "")),
                        start(node),
                        node.end_lineno or node.lineno,
                    )
                )
                visit(node.body, f"{prefix}{node.name}.", True)
            elif not in_class and isinstance(node, ast.Assign | ast.AnnAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if len(targets) == 1 and isinstance(targets[0], ast.Name):
                    symbols.append(
                        Symbol(
                            targets[0].id,
                            "const",
                            header(node),
                            "",
                            node.lineno,
                            node.end_lineno or node.lineno,
                        )
                    )

    visit(tree.body, "", False)
    return symbols


_DECLARATIONS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "type",
}


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


def _leading_comment(node: Node) -> str:
    previous = node.prev_named_sibling
    if node.parent is not None and node.parent.type == "export_statement":
        previous = node.parent.prev_named_sibling
        anchor_row = node.parent.start_point[0]
    else:
        anchor_row = node.start_point[0]
    if previous is None or previous.type != "comment" or previous.end_point[0] != anchor_row - 1:
        return ""
    for raw in _text(previous).splitlines():
        cleaned = raw.strip().lstrip("/*").strip().rstrip("*/").strip()
        if cleaned and not cleaned.startswith("@"):
            return _clip(cleaned)
    return ""


def _ts_symbol(node: Node, name: str, kind: str, prefix: str) -> Symbol:
    outer = (
        node.parent if node.parent is not None and node.parent.type == "export_statement" else node
    )
    return Symbol(
        prefix + name,
        kind,
        _first_line(_text(outer)),
        _leading_comment(node),
        outer.start_point[0] + 1,
        outer.end_point[0] + 1,
    )


def _ts_variable_symbols(node: Node, prefix: str) -> list[Symbol]:
    symbols = []
    exported = node.parent is not None and node.parent.type == "export_statement"
    for child in node.named_children:
        if child.type != "variable_declarator":
            continue
        name_node = child.child_by_field_name("name")
        value = child.child_by_field_name("value")
        if name_node is None or name_node.type != "identifier":
            continue
        is_function = value is not None and value.type in (
            "arrow_function",
            "function_expression",
            "function",
        )
        if is_function or exported:
            kind = "function" if is_function else "const"
            symbols.append(_ts_symbol(node, _text(name_node), kind, prefix))
    return symbols


def _ts_visit(parent: Node, prefix: str, symbols: list[Symbol]) -> None:
    for node in parent.named_children:
        current = node
        if node.type == "export_statement":
            declaration = node.child_by_field_name("declaration")
            if declaration is None:
                continue
            current = declaration
        kind = _DECLARATIONS.get(current.type)
        name_node = current.child_by_field_name("name")
        if kind and name_node is not None:
            name = _text(name_node)
            symbols.append(_ts_symbol(current, name, kind, prefix))
            body = current.child_by_field_name("body")
            if kind == "class" and body is not None:
                for member in body.named_children:
                    member_name = member.child_by_field_name("name")
                    if member.type == "method_definition" and member_name is not None:
                        symbols.append(
                            _ts_symbol(member, _text(member_name), "method", f"{prefix}{name}.")
                        )
        elif current.type == "lexical_declaration":
            symbols.extend(_ts_variable_symbols(current, prefix))


def _typescript_symbols(source: bytes, extension: str) -> list[Symbol]:
    tree = Parser(_TS_LANGUAGES[extension]).parse(source)
    symbols: list[Symbol] = []
    _ts_visit(tree.root_node, "", symbols)
    return symbols


def parse_symbols(path: str, data: bytes) -> list[Symbol]:
    """Symbols in line order. Raises SyntaxError for Python source that does not parse."""
    extension = PurePosixPath(path).suffix
    if extension in PYTHON_EXTENSIONS:
        symbols = _python_symbols(data.decode("utf-8", errors="replace"))
    else:
        symbols = _typescript_symbols(data, extension)
    return sorted(symbols, key=lambda s: (s.start_line, s.end_line))
