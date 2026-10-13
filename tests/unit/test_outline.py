from pathlib import Path

import pytest

from milepost.errors import NotFoundError, UsageError
from milepost.services.outline import MAX_SYMBOLS, outline_file
from milepost.structure.outline import Symbol

PY = '''"""Module doc."""

router = APIRouter(prefix="/billing")


def helper(x):
    """Adds one.

    More text.
    """
    return x + 1


@router.get("/charge")
async def charge(card: str) -> str:
    return card


class Account(Base):
    """A customer account."""

    def balance(self) -> int:
        return 0

    @property
    def name(self) -> str:
        return "x"
'''

TS = """// Adds numbers.
export function add(a: number, b: number): number {
  return a + b;
}

/** A thing. */
export class Widget {
  render(): string {
    return "w";
  }
}

export interface Props {
  id: string;
}

export type Id = string;

export const handler = async (req: Request) => {
  return req;
};

export const LIMIT = 10;
const hidden = 3;
"""


def write(tmp_path: Path, name: str, text: str) -> None:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def names(symbols: list[Symbol]) -> dict[str, Symbol]:
    return {symbol.name: symbol for symbol in symbols}


def test_outline_when_python_file_then_symbols_with_line_ranges(tmp_path: Path) -> None:
    write(tmp_path, "app/billing.py", PY)

    result = outline_file(tmp_path, "app/billing.py")

    symbols = names(result.symbols)
    assert symbols["router"].kind == "const"
    assert symbols["helper"].kind == "function"
    assert (symbols["helper"].start_line, symbols["helper"].end_line) == (6, 11)
    assert symbols["helper"].doc == "Adds one."
    assert symbols["helper"].signature == "def helper(x):"
    assert result.line_count == len(PY.splitlines())
    assert result.truncated is False


def test_outline_when_decorated_function_then_range_starts_at_decorator(tmp_path: Path) -> None:
    write(tmp_path, "app/billing.py", PY)

    charge = names(outline_file(tmp_path, "app/billing.py").symbols)["charge"]

    assert charge.start_line == 14
    assert charge.signature == "async def charge(card: str) -> str:"


def test_outline_when_class_with_methods_then_methods_listed_with_qualified_names(
    tmp_path: Path,
) -> None:
    write(tmp_path, "app/billing.py", PY)

    symbols = names(outline_file(tmp_path, "app/billing.py").symbols)

    assert symbols["Account"].kind == "class"
    assert symbols["Account"].doc == "A customer account."
    assert symbols["Account.balance"].kind == "method"
    assert symbols["Account.name"].start_line < symbols["Account.name"].end_line
    assert [s.start_line for s in outline_file(tmp_path, "app/billing.py").symbols] == sorted(
        s.start_line for s in outline_file(tmp_path, "app/billing.py").symbols
    )


def test_outline_when_typescript_file_then_functions_classes_and_exported_consts_listed(
    tmp_path: Path,
) -> None:
    write(tmp_path, "web/mod.ts", TS)

    symbols = names(outline_file(tmp_path, "web/mod.ts").symbols)

    assert symbols["add"].kind == "function"
    assert symbols["add"].doc == "Adds numbers."
    assert symbols["Widget"].kind == "class"
    assert symbols["Widget"].doc == "A thing."
    assert symbols["Widget.render"].kind == "method"
    assert symbols["Props"].kind == "interface"
    assert symbols["Id"].kind == "type"
    assert symbols["handler"].kind == "function"
    assert symbols["LIMIT"].kind == "const"
    assert "hidden" not in symbols


def test_outline_when_file_edited_then_new_line_ranges_returned(tmp_path: Path) -> None:
    write(tmp_path, "app/billing.py", PY)
    before = names(outline_file(tmp_path, "app/billing.py").symbols)["helper"].start_line

    write(tmp_path, "app/billing.py", "# new header\n# another\n" + PY)

    after = names(outline_file(tmp_path, "app/billing.py").symbols)["helper"].start_line
    assert after == before + 2


def test_outline_when_over_200_symbols_then_truncated_flag_set(tmp_path: Path) -> None:
    write(tmp_path, "big.py", "".join(f"def f{i}():\n    pass\n" for i in range(MAX_SYMBOLS + 5)))

    result = outline_file(tmp_path, "big.py")

    assert result.truncated is True
    assert len(result.symbols) == MAX_SYMBOLS


def test_outline_when_unsupported_extension_then_usage_error_with_line_count(
    tmp_path: Path,
) -> None:
    write(tmp_path, "notes.rb", "a\nb\nc\n")

    with pytest.raises(UsageError, match="3 lines"):
        outline_file(tmp_path, "notes.rb")


def test_outline_when_python_does_not_parse_then_usage_error_with_line_count(
    tmp_path: Path,
) -> None:
    write(tmp_path, "bad.py", "def (:\n")

    with pytest.raises(UsageError, match="does not parse"):
        outline_file(tmp_path, "bad.py")


def test_outline_when_path_outside_repo_then_usage_error(tmp_path: Path) -> None:
    (tmp_path / "repo").mkdir()
    write(tmp_path, "outside.py", "x = 1\n")

    with pytest.raises(UsageError, match="outside the repository"):
        outline_file(tmp_path / "repo", "../outside.py")


def test_outline_when_file_missing_then_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        outline_file(tmp_path, "nope.py")


def test_outline_when_file_has_form_feed_or_bom_then_line_numbers_and_parse_correct(
    tmp_path: Path,
) -> None:
    source = "# header\x0c second page\ndef first():\n    pass\n\n\ndef second():\n    pass\n"
    (tmp_path / "ff.py").write_bytes(b"\xef\xbb\xbf" + source.encode("utf-8"))

    result = outline_file(tmp_path, "ff.py")

    symbols = names(result.symbols)
    assert (symbols["first"].start_line, symbols["second"].start_line) == (2, 6)
    assert symbols["second"].signature == "def second():"
    assert result.line_count == 7


def test_outline_when_signature_spans_lines_then_joined_into_one_line(tmp_path: Path) -> None:
    write(
        tmp_path,
        "sig.py",
        "def create_invoice(\n    customer,\n    amount: int = 0,\n) -> str:\n    return ''\n",
    )

    symbol = names(outline_file(tmp_path, "sig.py").symbols)["create_invoice"]

    assert symbol.signature == "def create_invoice( customer, amount: int = 0, ) -> str:"


def test_outline_when_function_defined_under_if_or_try_then_listed(tmp_path: Path) -> None:
    write(
        tmp_path,
        "cond.py",
        "if TYPE_CHECKING:\n    class Hint:\n        pass\n\n"
        "try:\n    import fast\nexcept ImportError:\n    def slow():\n        pass\n",
    )

    symbols = names(outline_file(tmp_path, "cond.py").symbols)

    assert {"Hint", "slow"} <= set(symbols)


def test_outline_when_typescript_class_decorated_then_signature_is_the_class_line(
    tmp_path: Path,
) -> None:
    write(tmp_path, "svc.ts", "@Injectable()\nexport class Foo {\n  run() {}\n}\n")

    symbols = names(outline_file(tmp_path, "svc.ts").symbols)

    assert symbols["Foo"].signature == "export class Foo {"


def test_outline_when_line_comment_ends_with_slash_then_not_truncated(tmp_path: Path) -> None:
    write(tmp_path, "c.ts", "// see https://x.io/\nexport function f() {}\n")

    assert names(outline_file(tmp_path, "c.ts").symbols)["f"].doc == "see https://x.io/"


def test_outline_when_var_function_expression_then_listed(tmp_path: Path) -> None:
    write(tmp_path, "v.js", "var legacy = function () { return 1; };\n")

    assert names(outline_file(tmp_path, "v.js").symbols)["legacy"].kind == "function"
