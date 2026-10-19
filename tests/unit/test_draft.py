from pathlib import Path

import pytest
from support.kb_repo import KbRepo

from milepost.config import Config, load_config
from milepost.errors import UsageError
from milepost.services.draft import (
    PROMPT_PATH,
    build_draft_packet,
    collect_sources,
    scan_for_secrets,
)


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


def test_packet_when_one_file_looks_like_a_key_then_only_that_file_is_withheld(
    tmp_path: Path,
) -> None:
    repo, config = make_repo(tmp_path)
    repo.write("app/billing/pay.py", 'KEY = "AKIAABCDEFGHIJKLMNOP"\n')

    packet = build_draft_packet(repo.root, config, "billing")

    assert packet.withheld == ["app/billing/pay.py"]
    assert "AKIAABCDEFGHIJKLMNOP" not in packet.sources_text
    assert "app/billing/pay.py" not in packet.sent_files
    assert "def charge" in packet.sources_text  # the other files are still included
    assert "Files withheld" in packet.truncation_notice
    assert "`app/billing/pay.py`" in packet.truncation_notice


def test_secret_scan_when_file_is_in_secret_scan_allow_then_it_is_sent(tmp_path: Path) -> None:
    repo, config = make_repo(tmp_path)
    repo.write(
        "app/billing/pay.py",
        'TOKEN_TYPE = "password_setup_token"\nPASSWORD_KEY = "abcdefghijklmnop"\n',
    )
    config.draft.secret_scan_allow = ["app/billing/pay.py"]

    packet = build_draft_packet(repo.root, config, "billing")

    assert "app/billing/pay.py" in packet.sent_files
    assert packet.withheld == [] and packet.truncation_notice == ""


def test_secret_scan_when_every_file_is_withheld_then_usage_error_names_the_config_key(
    tmp_path: Path,
) -> None:
    repo, config = make_repo(tmp_path)
    for path in list((repo.root / "app/billing").glob("*.py")):
        path.write_text('KEY = "AKIAABCDEFGHIJKLMNOP"\n')

    with pytest.raises(UsageError) as error:
        build_draft_packet(repo.root, config, "billing")

    assert "secret_scan_allow" in str(error.value)
    assert "AKIAABCDEFGHIJKLMNOP" not in str(error.value)


def test_packet_when_sources_exceed_budget_then_notice_names_outline_only_files(
    tmp_path: Path,
) -> None:
    repo, _ = make_repo(tmp_path, extra="\n[draft]\nmax_source_bytes = 30\n")
    repo.write("app/billing/b.py", "def second():\n    return 2\n" * 5)
    config = load_config(repo.root / "milepost.toml")

    packet = build_draft_packet(repo.root, config, "billing")

    assert "app/billing/b.py" in packet.outline_only
    assert packet.truncation_notice.startswith("> **Truncated draft.**")
    assert "`app/billing/b.py`" in packet.truncation_notice
    assert "max_source_bytes" in packet.truncation_notice


def test_packet_when_module_is_unknown_then_key_error_is_not_swallowed(tmp_path: Path) -> None:
    repo, config = make_repo(tmp_path)

    with pytest.raises(KeyError):
        build_draft_packet(repo.root, config, "nope")


def test_packet_when_prompt_built_then_includes_related_and_source_text(tmp_path: Path) -> None:
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

    packet = build_draft_packet(repo.root, config, "billing")

    assert "Related modules" in packet.system_prompt and "accounts" in packet.system_prompt
    assert "def charge(card)" in packet.sources_text


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


def test_packet_when_built_then_carries_the_read_receipt(tmp_path: Path) -> None:
    repo, config = make_repo(tmp_path)

    packet = build_draft_packet(repo.root, config, "billing")

    assert packet.source_hash_now == repo.hash_of(["app/billing/**"])
    assert "app/billing/api.py" in packet.sent_files
    assert "STRIPE_KEY" not in packet.sources_text  # draft.exclude keeps .env files out
