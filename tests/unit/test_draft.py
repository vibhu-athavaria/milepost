import json
from pathlib import Path

import pytest
from support.kb_repo import KbRepo

from milepost.config import Config, load_config
from milepost.core.notes import read_note
from milepost.errors import ProviderError, SecretDetected, UsageError
from milepost.llm.client import complete_with_retries
from milepost.services.draft import (
    PROMPT_PATH,
    collect_sources,
    draft_modules,
    scan_for_secrets,
)

BODY = "## Purpose\n\nBills customers.\n\n## Entry points\n\n- app/billing/api.py\n"
NOW = "2026-10-10T09:00:00Z"


class FakeClient:
    """Fails `failures` times, then returns `reply`. Records every call."""

    def __init__(self, reply: str = BODY, failures: int = 0, fail_for: str | None = None) -> None:
        self.reply = reply
        self.failures = failures
        self.fail_for = fail_for
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, model: str, system: str, user: str) -> str:
        self.calls.append((model, system, user))
        if self.fail_for is not None and self.fail_for in user:
            raise RuntimeError("provider down")
        if len(self.calls) <= self.failures:
            raise RuntimeError("provider down")
        return self.reply


def no_sleep(seconds: float) -> None:
    pass


def make_repo(tmp_path: Path, extra: str = "") -> tuple[KbRepo, Config]:
    repo = KbRepo(tmp_path / "repo", extra_config=extra)
    repo.add_module(
        "billing",
        ["app/billing/**"],
        {
            "app/billing/api.py": "def charge(card):\n    return card\n",
            "app/billing/.env": "STRIPE_KEY=live\n",
        },
        with_note=False,
    )
    return repo, load_config(repo.root / "milepost.toml")


def test_collect_sources_when_exclude_matches_env_file_then_file_not_sent(tmp_path: Path) -> None:
    repo, config = make_repo(tmp_path)

    collected = collect_sources(repo.root, config, "billing")

    assert collected.sent == ["app/billing/api.py"]
    assert collected.excluded == ["app/billing/.env"]
    assert "STRIPE_KEY" not in collected.text


def test_collect_sources_when_over_budget_then_truncates_and_notes_truncation(
    tmp_path: Path,
) -> None:
    repo, _ = make_repo(tmp_path, extra="\n[draft]\nmax_source_bytes = 120\n")
    repo.write("app/billing/a.py", "def first():\n    return 1\n" + "# pad\n" * 5)
    repo.write("app/billing/b.py", "class Second:\n    def run(self):\n        return 2\n" * 10)
    config = load_config(repo.root / "milepost.toml")

    collected = collect_sources(repo.root, config, "billing")

    assert collected.truncated is True
    assert "=== app/billing/b.py (outline only) ===" in collected.text
    assert "class Second:" in collected.text
    assert "return 2" not in collected.text


def test_collect_sources_when_within_budget_then_not_truncated(tmp_path: Path) -> None:
    repo, config = make_repo(tmp_path)

    assert collect_sources(repo.root, config, "billing").truncated is False


def test_scan_for_secrets_when_aws_key_pattern_then_names_file_only() -> None:
    found = scan_for_secrets(
        {"app/pay.py": 'KEY = "AKIAABCDEFGHIJKLMNOP"\n', "app/ok.py": "x = 1\n"}
    )

    assert found == "app/pay.py"


@pytest.mark.parametrize(
    "text",
    [
        "-----BEGIN RSA PRIVATE KEY-----\nabc\n",
        'password = "correct-horse-battery"\n',
        'API_TOKEN: "abcdefghijklmnop1234"\n',
        "sk-abcdefghijklmnopqrstuvwx\n",
    ],
)
def test_scan_for_secrets_when_common_secret_shapes_then_found(text: str) -> None:
    assert scan_for_secrets({"f.py": text}) == "f.py"


def test_scan_for_secrets_when_ordinary_code_then_none() -> None:
    assert scan_for_secrets({"f.py": "password = get_password()\ntoken_count = 3\n"}) is None


def test_secret_scan_when_aws_key_pattern_then_aborts_module_with_file_name_only(
    tmp_path: Path,
) -> None:
    repo, config = make_repo(tmp_path)
    repo.write("app/billing/pay.py", 'KEY = "AKIAABCDEFGHIJKLMNOP"\n')
    client = FakeClient()

    with pytest.raises(SecretDetected) as error:
        draft_modules(repo.root, config, ["billing"], client, "m", False, NOW, no_sleep)

    assert error.value.exit_code == 4
    assert "app/billing/pay.py" in str(error.value)
    assert "AKIAABCDEFGHIJKLMNOP" not in str(error.value)
    assert client.calls == []


def test_draft_when_provider_fails_twice_then_retries_and_succeeds(tmp_path: Path) -> None:
    client = FakeClient(failures=2)
    sleeps: list[float] = []

    reply = complete_with_retries(client, "m", "s", "u", sleep=sleeps.append)

    assert reply == BODY
    assert len(client.calls) == 3
    assert sleeps == sorted(sleeps) and len(sleeps) == 2


def test_draft_when_provider_fails_three_times_then_exit_four_and_progress_saved(
    tmp_path: Path,
) -> None:
    repo, _ = make_repo(tmp_path)
    repo.add_module("accounts", ["app/accounts/**/*.py"], {"app/accounts/m.py": "x = 1\n"}, False)
    config = load_config(repo.root / "milepost.toml")
    client = FakeClient(fail_for="app/accounts/m.py")

    with pytest.raises(ProviderError) as error:
        draft_modules(repo.root, config, ["billing", "accounts"], client, "m", False, NOW, no_sleep)

    assert error.value.exit_code == 4
    assert "accounts" in str(error.value)
    assert (repo.root / "kb/modules/billing.md").is_file()
    assert not (repo.root / "kb/modules/accounts.md").exists()
    progress = json.loads((repo.root / "kb/.progress.json").read_text())
    assert progress["completed"] == ["billing"]


def test_draft_when_note_reviewed_and_no_force_then_refuses(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path)
    repo.write_note_file("kb/modules/billing.md", "module/billing", "L2", ["app/billing/**"])
    config = load_config(repo.root / "milepost.toml")
    client = FakeClient()

    with pytest.raises(UsageError, match="reviewed"):
        draft_modules(repo.root, config, ["billing"], client, "m", False, NOW, no_sleep)

    assert client.calls == []
    assert read_note(repo.root / "kb/modules/billing.md").meta["status"] == "reviewed"


def test_draft_when_note_reviewed_and_force_then_overwritten_as_draft(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path)
    repo.write_note_file("kb/modules/billing.md", "module/billing", "L2", ["app/billing/**"])
    config = load_config(repo.root / "milepost.toml")

    draft_modules(repo.root, config, ["billing"], FakeClient(), "m", True, NOW, no_sleep)

    assert read_note(repo.root / "kb/modules/billing.md").meta["status"] == "draft"


def test_draft_when_run_then_frontmatter_written_by_milepost_not_model(tmp_path: Path) -> None:
    repo, config = make_repo(tmp_path)
    reply = "---\nstatus: reviewed\nsource_hash: sha256:fake\nwritten_by: human\n---\n" + BODY
    client = FakeClient(reply=reply)

    draft_modules(repo.root, config, ["billing"], client, "m", False, NOW, no_sleep)

    note = read_note(repo.root / "kb/modules/billing.md")
    assert note.meta["status"] == "draft"
    assert note.meta["written_by"] == "draft-command"
    assert note.meta["written_at"] == NOW
    assert note.meta["id"] == "module/billing"
    assert note.meta["sources"] == ["app/billing/**"]
    assert note.meta["source_hash"] == repo.hash_of(["app/billing/**"])
    assert "Bills customers" in note.body
    assert "sha256:fake" not in note.body


def test_draft_when_sources_truncated_then_notice_is_first_and_names_outline_only_files(
    tmp_path: Path,
) -> None:
    repo, _ = make_repo(tmp_path, extra="\n[draft]\nmax_source_bytes = 30\n")
    repo.write("app/billing/b.py", "def second():\n    return 2\n" * 5)
    config = load_config(repo.root / "milepost.toml")

    draft_modules(repo.root, config, ["billing"], FakeClient(), "m", False, NOW, no_sleep)

    body = read_note(repo.root / "kb/modules/billing.md").body.strip()
    assert body.startswith("> **Truncated draft.**")
    assert "`app/billing/b.py`" in body.split("\n\n")[0]
    assert "max_source_bytes" in body.split("\n\n")[0]


def test_draft_when_model_reply_empty_then_provider_error(tmp_path: Path) -> None:
    repo, config = make_repo(tmp_path)

    with pytest.raises(ProviderError, match="empty"):
        draft_modules(
            repo.root, config, ["billing"], FakeClient(reply="  \n"), "m", False, NOW, no_sleep
        )


def test_draft_when_unknown_module_then_error(tmp_path: Path) -> None:
    repo, config = make_repo(tmp_path)

    with pytest.raises(UsageError, match="nope"):
        draft_modules(repo.root, config, ["nope"], FakeClient(), "m", False, NOW, no_sleep)


def test_draft_when_prompt_built_then_includes_related_and_source_text(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path, extra="")
    repo.add_module("accounts", ["app/accounts/**/*.py"], {"app/accounts/m.py": "x = 1\n"}, False)
    text = (
        (repo.root / "milepost.toml")
        .read_text()
        .replace(
            'sources = ["app/billing/**"]', 'sources = ["app/billing/**"]\nrelated = ["accounts"]'
        )
    )
    (repo.root / "milepost.toml").write_text(text)
    config = load_config(repo.root / "milepost.toml")
    client = FakeClient()

    draft_modules(repo.root, config, ["billing"], client, "m", False, NOW, no_sleep)

    _, system, user = client.calls[0]
    assert "Related modules" in system and "accounts" in system
    assert "def charge(card)" in user


def test_draft_prompt_when_loaded_then_has_l2_sections_in_order_including_file_map() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]

    assert headings == [
        "## Purpose",
        "## Entry points",
        "## File map",
        "## Owned data",
        "## Invariants",
        "## Gotchas",
        "## Related modules",
    ]
