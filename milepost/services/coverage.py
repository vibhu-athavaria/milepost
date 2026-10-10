"""Which source directories no module covers (SPEC sections 6 and 8)."""

from pathlib import Path

from milepost.config import Module, Structure, load_config
from milepost.core.glob import expand_sources
from milepost.structure.candidates import Candidate, scan_candidates

CONFIG_NAME = "milepost.toml"


def uncovered_candidates(
    root: Path, structure: Structure, modules: dict[str, Module]
) -> list[Candidate]:
    """Candidates where no declared module's sources match any file in the directory."""
    covered: set[str] = set()
    for module in modules.values():
        covered.update(expand_sources(root, module.sources, structure.ignore))
    return [
        candidate
        for candidate in scan_candidates(root, structure)
        if not covered.intersection(expand_sources(root, candidate.sources, structure.ignore))
    ]


def undeclared_candidates(root: Path) -> list[Candidate]:
    """Uncovered candidates for a repository, using defaults when it has no milepost.toml yet."""
    config_path = root / CONFIG_NAME
    if config_path.is_file():
        config = load_config(config_path)
        return uncovered_candidates(root, config.structure, config.modules)
    return uncovered_candidates(root, Structure(), {})
