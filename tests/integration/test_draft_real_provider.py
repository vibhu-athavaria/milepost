"""Calls a real provider. Skipped unless MILEPOST_MODEL and the provider key are available."""

import os
from pathlib import Path

import pytest
from support.kb_repo import KbRepo

from milepost.config import load_config
from milepost.core.notes import read_note
from milepost.env import load_env
from milepost.llm.client import LiteLlmClient
from milepost.services.doctor import litellm_missing_keys
from milepost.services.draft import draft_modules

load_env(Path(__file__).resolve().parents[2])


def _ready() -> bool:
    model = os.environ.get("MILEPOST_MODEL")
    return bool(model) and not litellm_missing_keys(str(model))


pytestmark = pytest.mark.skipif(
    not _ready(), reason="set MILEPOST_MODEL and the provider key (shell or .env) to run"
)


def test_draft_when_real_provider_then_note_written_as_draft(tmp_path: Path) -> None:
    repo = KbRepo(tmp_path / "repo")
    repo.add_module(
        "billing",
        ["app/billing/**/*.py"],
        {"app/billing/api.py": "def charge(card):\n    return card.amount\n"},
        with_note=False,
    )
    config = load_config(repo.root / "milepost.toml")

    draft_modules(
        repo.root,
        config,
        ["billing"],
        LiteLlmClient(),
        os.environ["MILEPOST_MODEL"],
        False,
        "2026-10-10T09:00:00Z",
        lambda seconds: None,
    )

    note = read_note(repo.root / "kb/modules/billing.md")
    assert note.meta["status"] == "draft"
    assert note.body.strip()
