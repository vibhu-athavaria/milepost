from pathlib import Path

import pytest
from support.kb_repo import KbRepo

from milepost.config import load_config
from milepost.errors import NotFoundError
from milepost.services.impact import MAX_ITEMS, ImpactResult, file_impact, is_test_path

IMPORT = "from app.billing.charge import charge\n"
ROUTES = IMPORT + "\n\ndef go():\n    return charge(1)\n"
TEST_CHARGE = IMPORT + "\n\ndef test_it():\n    assert charge(1)\n"


def make_repo(tmp_path: Path, extra_config: str = "") -> KbRepo:
    repo = KbRepo(tmp_path / "repo", extra_config=extra_config)
    repo.add_module(
        "billing",
        ["app/billing/**/*.py"],
        {
            "app/billing/charge.py": "def charge(card):\n    return card\n",
            "app/api/routes.py": ROUTES,
            "app/other.py": "x = 1\n",
            "tests/test_charge.py": TEST_CHARGE,
            "tests/test_charge_extra.py": "def test_extra():\n    assert True\n",
        },
    )
    return repo


def impact(repo: KbRepo, path: str) -> ImpactResult:
    return file_impact(repo.root, load_config(repo.root / "milepost.toml"), path)


def test_impact_when_file_imported_then_importers_listed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = impact(repo, "app/billing/charge.py")

    assert result.importers == ["app/api/routes.py", "tests/test_charge.py"]
    assert "app/other.py" not in result.importers


def test_impact_when_test_file_imports_target_then_listed_as_test_via_import(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)

    tests = {t.path: t.via for t in impact(repo, "app/billing/charge.py").tests}

    assert tests["tests/test_charge.py"] == "import"


def test_impact_when_test_name_contains_stem_then_listed_as_test_via_name(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    tests = {t.path: t.via for t in impact(repo, "app/billing/charge.py").tests}

    assert tests["tests/test_charge_extra.py"] == "name"


def test_impact_when_over_50_importers_then_truncated_flag_set(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    for i in range(MAX_ITEMS + 5):
        repo.write(f"app/many/u{i}.py", "from app.billing.charge import charge\n")

    result = impact(repo, "app/billing/charge.py")

    assert result.truncated is True
    assert len(result.importers) == MAX_ITEMS


def test_impact_when_path_unknown_then_not_found(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(NotFoundError):
        impact(repo, "app/nope.py")


def test_impact_when_module_has_verify_commands_then_returned(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    text = (
        (repo.root / "milepost.toml")
        .read_text()
        .replace(
            'sources = ["app/billing/**/*.py"]',
            'sources = ["app/billing/**/*.py"]\nverify = ["pytest tests/test_charge.py"]',
        )
    )
    (repo.root / "milepost.toml").write_text(text)

    result = impact(repo, "app/billing/charge.py")

    assert [(m.id, m.verify) for m in result.modules] == [
        ("billing", ["pytest tests/test_charge.py"])
    ]
    assert result.notes == ["module/billing"]


def test_impact_when_package_init_imported_by_package_name_then_found(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write("app/billing/__init__.py", "")
    repo.write("app/use_pkg.py", "import app.billing\n")

    assert "app/use_pkg.py" in impact(repo, "app/billing/__init__.py").importers


def test_impact_when_typescript_file_then_importers_found(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, extra_config='\n[structure]\nlanguages = ["python", "typescript"]\n')
    repo.write("web/util.ts", "export const x = 1;\n")
    repo.write("web/page.ts", "import { x } from './util';\n")

    assert impact(repo, "web/util.ts").importers == ["web/page.ts"]


@pytest.mark.parametrize(
    "path",
    [
        "tests/a.py",
        "pkg/__tests__/a.ts",
        "a/test_b.py",
        "a/b_test.py",
        "web/a.test.ts",
        "web/a.spec.js",
    ],
)
def test_is_test_path_when_test_like_then_true(path: str) -> None:
    assert is_test_path(path)


@pytest.mark.parametrize("path", ["app/latest.py", "app/contest.py", "web/protest.ts"])
def test_is_test_path_when_name_only_resembles_then_false(path: str) -> None:
    assert not is_test_path(path)


def test_impact_when_importer_is_in_git_ignored_dir_then_not_listed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.write(".gitignore", ".claude/worktrees/\n")
    repo.write(".claude/worktrees/copy/app/use.py", IMPORT)
    repo.write(".claude/worktrees/copy/tests/test_charge.py", IMPORT)

    result = impact(repo, "app/billing/charge.py")

    assert all(not p.startswith(".claude/") for p in result.importers)
    assert all(not t.path.startswith(".claude/") for t in result.tests)


def test_impact_when_not_a_git_repo_then_falls_back_to_globbing(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    for path in (repo.root / ".git").glob("**/*"):
        if path.is_file():
            path.unlink()
    (repo.root / ".git").rename(repo.root / "renamed-git")

    result = impact(repo, "app/billing/charge.py")

    assert "app/api/routes.py" in result.importers
