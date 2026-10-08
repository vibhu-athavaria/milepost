from pathlib import Path

from kbmap.config import Structure
from kbmap.structure.base import ScanResult
from kbmap.structure.candidates import scan_candidates
from kbmap.structure.python_scanner import scan_python
from kbmap.structure.tree_sitter_scanner import scan_typescript

SAMPLE_REPO = Path(__file__).parent.parent / "fixtures" / "sample_repo"


def make_repo(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def edge_set(result: ScanResult) -> set[tuple[str, str]]:
    return {(edge.target, edge.kind) for edge in result.edges}


def test_python_scanner_when_import_statements_then_returns_module_edges(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/a.py": "import app.b\nimport os\nfrom app import c\n",
            "app/b.py": "",
            "app/c.py": "",
        },
    )

    result = scan_python(tmp_path, ["app/a.py"])

    assert edge_set(result) == {
        ("app/b.py", "internal"),
        ("os", "external"),
        ("app/c.py", "internal"),
    }
    assert {edge.source for edge in result.edges} == {"app/a.py"}


def test_python_scanner_when_relative_import_then_resolves_to_repo_path(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        {
            "app/sub/x.py": "from . import y\nfrom .m import q\nfrom .. import top\n",
            "app/sub/y.py": "",
            "app/sub/m.py": "",
            "app/top.py": "",
        },
    )

    result = scan_python(tmp_path, ["app/sub/x.py"])

    assert edge_set(result) == {
        ("app/sub/y.py", "internal"),
        ("app/sub/m.py", "internal"),
        ("app/top.py", "internal"),
    }


def test_python_scanner_when_package_below_repo_root_then_resolves_absolute_import(
    tmp_path: Path,
) -> None:
    make_repo(
        tmp_path,
        {"backend/app/ai/t.py": "", "backend/app/services/s.py": "from app.ai import t\n"},
    )

    result = scan_python(tmp_path, ["backend/app/services/s.py"])

    assert edge_set(result) == {("backend/app/ai/t.py", "internal")}


def test_python_scanner_when_syntax_error_then_reports_file_and_continues(tmp_path: Path) -> None:
    make_repo(tmp_path, {"bad.py": "def (:\n", "good.py": "import os\n"})

    result = scan_python(tmp_path, ["bad.py", "good.py"])

    assert edge_set(result) == {("os", "external")}
    assert len(result.errors) == 1
    assert result.errors[0].startswith("bad.py")


def test_ts_scanner_when_import_from_then_returns_module_edges(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        {
            "src/a.ts": (
                "import { x } from './b';\nimport React from 'react';\nexport * from './c';\n"
            ),
            "src/b.ts": "",
            "src/c.tsx": "",
        },
    )

    result = scan_typescript(tmp_path, ["src/a.ts"])

    assert edge_set(result) == {
        ("src/b.ts", "internal"),
        ("react", "external"),
        ("src/c.tsx", "internal"),
    }


def test_ts_scanner_when_index_file_then_resolves_directory_import(tmp_path: Path) -> None:
    make_repo(tmp_path, {"src/a.ts": "import { x } from './lib';\n", "src/lib/index.ts": ""})

    assert edge_set(scan_typescript(tmp_path, ["src/a.ts"])) == {("src/lib/index.ts", "internal")}


def test_ts_scanner_when_dynamic_import_then_marks_edge_unresolved(tmp_path: Path) -> None:
    make_repo(tmp_path, {"src/a.ts": "const m = await import(name);\nimport('./b');\n"})

    result = scan_typescript(tmp_path, ["src/a.ts"])

    assert edge_set(result) == {("name", "unresolved"), ("./b", "unresolved")}


def test_scanners_when_sample_repo_then_return_expected_edges() -> None:
    python = scan_python(SAMPLE_REPO, ["app/services/lessons.py"])
    typescript = scan_typescript(SAMPLE_REPO, ["web/src/index.ts"])

    assert edge_set(python) == {
        ("os", "external"),
        ("app/ai/tutor.py", "internal"),
        ("app/services/helpers.py", "internal"),
    }
    assert edge_set(typescript) == {
        ("web/src/util.ts", "internal"),
        ("react", "external"),
        ("name", "unresolved"),
    }


def test_scan_candidates_when_app_directory_then_proposes_module_per_subdirectory(
    tmp_path: Path,
) -> None:
    make_repo(tmp_path, {"app/services/a.py": "", "app/ai/b.py": "", "app/readme.md": ""})

    candidates = scan_candidates(tmp_path, Structure())

    assert {candidate.id for candidate in candidates} == {"services", "ai"}
    services = next(candidate for candidate in candidates if candidate.id == "services")
    assert services.path == "app/services"
    assert services.sources == ["app/services/**/*.py"]


def test_scan_candidates_when_directory_has_no_source_files_then_not_proposed(
    tmp_path: Path,
) -> None:
    make_repo(tmp_path, {"app/docs/readme.md": "", "app/node_modules/x/i.js": ""})

    assert scan_candidates(tmp_path, Structure(languages=["python", "javascript"])) == []


def test_scan_candidates_when_ids_collide_across_roots_then_ids_stay_unique(
    tmp_path: Path,
) -> None:
    make_repo(tmp_path, {"src/core/a.py": "", "packages/core/b.py": ""})

    ids = [candidate.id for candidate in scan_candidates(tmp_path, Structure())]

    assert len(ids) == len(set(ids)) == 2


def test_scan_candidates_when_candidates_proposed_then_none_marked_active(tmp_path: Path) -> None:
    make_repo(tmp_path, {"app/services/a.py": "", "src/web/b.ts": ""})

    candidates = scan_candidates(tmp_path, Structure(languages=["python", "typescript"]))

    assert candidates
    assert all(not candidate.active for candidate in candidates)
