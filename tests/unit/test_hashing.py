import hashlib
import sys
from pathlib import Path

import pytest

from milepost.core.hashing import compute_source_hash

EMPTY = "sha256:" + hashlib.sha256(b"").hexdigest()


def make_repo(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def hash_of(root: Path, sources: list[str], ignore: list[str] | None = None) -> str:
    return compute_source_hash(root, sources, ignore or []).value


def test_source_hash_when_same_content_then_same_hash_on_repeat_runs(tmp_path: Path) -> None:
    make_repo(tmp_path, {"a.py": b"x = 1\n", "b.py": b"y = 2\n"})

    assert hash_of(tmp_path, ["*.py"]) == hash_of(tmp_path, ["*.py"])


def test_source_hash_when_crlf_and_lf_then_same_hash(tmp_path: Path) -> None:
    lf = make_repo(tmp_path / "lf", {"a.py": b"x = 1\ny = 2\n"})
    crlf = make_repo(tmp_path / "crlf", {"a.py": b"x = 1\r\ny = 2\r\n"})
    lone_cr = make_repo(tmp_path / "cr", {"a.py": b"x = 1\ry = 2\r"})

    assert hash_of(lf, ["*.py"]) == hash_of(crlf, ["*.py"]) == hash_of(lone_cr, ["*.py"])


def test_source_hash_when_file_added_then_hash_changes(tmp_path: Path) -> None:
    make_repo(tmp_path, {"a.py": b"x = 1\n"})
    before = hash_of(tmp_path, ["*.py"])

    make_repo(tmp_path, {"b.py": b"y = 2\n"})

    assert hash_of(tmp_path, ["*.py"]) != before


def test_source_hash_when_file_order_differs_then_hash_same(tmp_path: Path) -> None:
    first = make_repo(tmp_path / "one", {})
    second = make_repo(tmp_path / "two", {})
    for name in ["c.py", "a.py", "b.py"]:
        make_repo(first, {name: name.encode()})
    for name in ["a.py", "b.py", "c.py"]:
        make_repo(second, {name: name.encode()})

    assert hash_of(first, ["*.py"]) == hash_of(second, ["*.py"])
    assert hash_of(first, ["b.py", "*.py"]) == hash_of(first, ["*.py"])


def test_source_hash_when_no_files_match_then_returns_empty_digest_and_warns(
    tmp_path: Path,
) -> None:
    result = compute_source_hash(tmp_path, ["nothing/**/*.py"], [])

    assert result.value == EMPTY
    assert result.manifest == {}
    assert any("matches no files" in warning for warning in result.warnings)


def test_source_hash_when_ignore_pattern_matches_then_file_excluded(tmp_path: Path) -> None:
    make_repo(tmp_path, {"a.py": b"x\n", "node_modules/dep/i.py": b"ignored\n"})

    result = compute_source_hash(tmp_path, ["**/*.py"], ["**/node_modules/**"])

    assert list(result.manifest) == ["a.py"]


def test_source_hash_when_binary_file_then_no_newline_normalization(tmp_path: Path) -> None:
    crlf = make_repo(tmp_path / "crlf", {"d.bin": b"\x00\r\n\x01"})
    lf = make_repo(tmp_path / "lf", {"d.bin": b"\x00\n\x01"})

    assert hash_of(crlf, ["*.bin"]) != hash_of(lf, ["*.bin"])


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_source_hash_when_symlink_then_hashes_target_content_under_link_name(
    tmp_path: Path,
) -> None:
    linked = make_repo(tmp_path / "linked", {"real.py": b"x = 1\n"})
    (linked / "alias.py").symlink_to(linked / "real.py")
    plain = make_repo(tmp_path / "plain", {"alias.py": b"x = 1\n"})

    result = compute_source_hash(linked, ["alias.py"], [])

    assert list(result.manifest) == ["alias.py"]
    assert result.value == hash_of(plain, ["alias.py"])


def test_source_hash_when_trailing_whitespace_changed_then_hash_changes(tmp_path: Path) -> None:
    make_repo(tmp_path, {"a.py": b"x = 1\n"})
    before = hash_of(tmp_path, ["a.py"])

    make_repo(tmp_path, {"a.py": b"x = 1 \n"})

    assert hash_of(tmp_path, ["a.py"]) != before


def test_source_hash_when_dotfile_matches_then_included(tmp_path: Path) -> None:
    make_repo(tmp_path, {".hidden.py": b"x\n"})

    assert list(compute_source_hash(tmp_path, ["*.py"], []).manifest) == [".hidden.py"]


def test_source_hash_when_directory_matches_glob_then_not_hashed(tmp_path: Path) -> None:
    make_repo(tmp_path, {"pkg/a.py": b"x\n"})

    assert list(compute_source_hash(tmp_path, ["*"], []).manifest) == []
