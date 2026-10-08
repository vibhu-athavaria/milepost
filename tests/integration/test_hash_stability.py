from pathlib import Path

from kbmap.core.hashing import compute_source_hash

FIXTURE = Path(__file__).parent.parent / "fixtures" / "hash_repo"

# Computed by an independent reference script written from SPEC section 5, not by kbmap.
# Regenerate only deliberately, with a commit note explaining why the algorithm changed.
EXPECTED = "sha256:2226ee030923b45eebf6c15f110e815d7ff112f885f56451ed89bb00fa0a5cbb"


def test_source_hash_when_fixture_repo_then_matches_hard_coded_value() -> None:
    result = compute_source_hash(FIXTURE, ["**/*.py", "**/*.bin"], ["**/node_modules/**"])

    assert list(result.manifest) == ["a.py", "pkg/b.py", "pkg/data.bin"]
    assert result.value == EXPECTED
