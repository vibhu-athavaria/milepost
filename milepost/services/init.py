"""`milepost init`: scaffold the knowledge base, declare modules, draft notes (SPEC section 9)."""

import json
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path

from milepost.config import Config, Module, Project, Structure, load_config, resolve_model
from milepost.embeddings import Embedder
from milepost.errors import EnvironmentProblem, UsageError
from milepost.llm.client import LlmClient
from milepost.services.coverage import CONFIG_NAME, uncovered_candidates, undeclared_candidates
from milepost.services.draft import collect_sources, draft_modules
from milepost.services.index import run_index
from milepost.structure.candidates import Candidate

GITIGNORE_LINES = ["kb/.index/", "kb/.progress.json", ".env"]
GITATTRIBUTES_LINE = "kb/**/*.md merge=milepost"
WORKFLOW_PATH = ".github/workflows/milepost.yml"
WORKFLOW_TEMPLATE = Path(__file__).resolve().parent.parent / "resources" / "ci-kb-check.yml"


@dataclass
class InitReport:
    dry_run: bool = False
    created: list[str] = field(default_factory=list)
    declared: list[str] = field(default_factory=list)
    drafted: list[str] = field(default_factory=list)
    planned_files: dict[str, list[str]] = field(default_factory=dict)
    outline_only: dict[str, list[str]] = field(default_factory=dict)
    estimated_tokens: int = 0
    indexed: int = 0


def _require_git_repo(root: Path) -> None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--git-dir"], cwd=root, capture_output=True, check=False
        )
    except FileNotFoundError as error:
        raise EnvironmentProblem("git is not installed or not on PATH") from error
    if done.returncode != 0:
        raise EnvironmentProblem(f"{root} is not a git repository; run `git init` first")


def _toml_list(values: list[str]) -> str:
    return "[" + ", ".join(json.dumps(value) for value in values) + "]"


def _module_table(candidate: Candidate, commented: bool) -> str:
    lines = [
        f"[modules.{candidate.id}]",
        f"title = {json.dumps(candidate.id)}",
        f"sources = {_toml_list(candidate.sources)}",
    ]
    prefix = "# " if commented else ""
    return "\n".join(f"{prefix}{line}" for line in lines) + "\n"


def _render_config(name: str, active: list[Candidate], suggested: list[Candidate]) -> str:
    defaults = Structure()
    parts = [
        "# milepost configuration. Commit this file.\n"
        "# Declare a module by uncommenting its table (or run `milepost init --modules <ids>`).\n",
        f'[project]\nname = {json.dumps(name)}\nkb_dir = "kb"\n',
    ]
    parts += [_module_table(candidate, commented=False) for candidate in active]
    parts += [_module_table(candidate, commented=True) for candidate in suggested]
    parts.append(
        "[structure]\n"
        f"languages = {_toml_list(defaults.languages)}\n"
        f"ignore = {_toml_list(defaults.ignore)}\n"
        f"roots = {_toml_list(defaults.roots)}\n"
    )
    parts.append(
        "[draft]\n"
        "# Resolved from the MILEPOST_MODEL environment variable (shell or .env). "
        "Never put a model name or key here.\n"
        'provider_model = "${MILEPOST_MODEL}"\n'
        "max_source_bytes = 200000\n"
        'exclude = ["**/.env*", "**/*secret*", "**/*.pem", "**/*.key", "**/credentials*"]\n'
    )
    return "\n".join(parts)


def _append_missing_lines(path: Path, lines: list[str]) -> bool:
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    present = set(existing.splitlines())
    missing = [line for line in lines if line not in present]
    if not missing:
        return False
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + prefix + "\n".join(missing) + "\n", encoding="utf-8")
    return True


def _workflow_text() -> str:
    return re.sub(
        r"milepost==[\w.]+", f"milepost=={version('milepost')}", WORKFLOW_TEMPLATE.read_text()
    )


def _plan_config(
    root: Path, wanted: list[str] | None, force_config: bool
) -> tuple[Config, list[Candidate], list[Candidate], bool]:
    """Returns (config as it will be, newly declared, still-suggested candidates, config exists)."""
    exists = (root / CONFIG_NAME).is_file() and not force_config
    candidates = (
        uncovered_candidates(root, Structure(), {}) if force_config else undeclared_candidates(root)
    )
    by_id = {candidate.id: candidate for candidate in candidates}
    config = (
        load_config(root / CONFIG_NAME)
        if exists
        else Config(project=Project(name=root.resolve().name))
    )
    declared_already = set(config.modules)
    newly: list[Candidate] = []
    for module_id in wanted or []:
        if module_id in declared_already:
            continue
        if module_id not in by_id:
            raise UsageError(
                f"'{module_id}' is not a current module candidate "
                f"(candidates: {', '.join(sorted(by_id)) or 'none'})"
            )
        newly.append(by_id[module_id])
    for candidate in newly:
        config.modules[candidate.id] = Module(sources=candidate.sources, title=candidate.id)
    suggested = [c for c in candidates if c.id not in {n.id for n in newly}]
    return config, newly, suggested, exists


def run_init(
    root: Path,
    *,
    modules: list[str] | None,
    dry_run: bool,
    force_config: bool,
    client: LlmClient,
    embedder: Embedder,
    environ: Mapping[str, str],
    now: str,
    sleep: Callable[[float], None],
) -> InitReport:
    _require_git_repo(root)
    config, newly, suggested, config_exists = _plan_config(root, modules, force_config)
    kb = root / config.project.kb_dir
    to_draft = [m for m in config.modules if not (kb / "modules" / f"{m}.md").is_file()]
    report = InitReport(dry_run=dry_run, declared=[c.id for c in newly])

    if dry_run:
        for module_id in to_draft:
            collected = collect_sources(root, config, module_id)
            report.planned_files[module_id] = collected.sent
            if collected.outline_only:
                report.outline_only[module_id] = collected.outline_only
            report.estimated_tokens += collected.estimated_tokens
        return report

    model = resolve_model(config, environ) if to_draft else ""

    config_path = root / CONFIG_NAME
    if not config_exists:
        config_path.write_text(_render_config(config.project.name, newly, suggested))
        report.created.append(CONFIG_NAME)
    elif newly:
        existing = config_path.read_text(encoding="utf-8")
        joiner = "" if existing.endswith("\n") else "\n"
        tables = "\n".join(_module_table(candidate, commented=False) for candidate in newly)
        config_path.write_text(existing + joiner + "\n" + tables, encoding="utf-8")
    if not kb.is_dir():
        (kb / "modules").mkdir(parents=True)
        report.created.append(config.project.kb_dir + "/")
    if _append_missing_lines(root / ".gitignore", GITIGNORE_LINES):
        report.created.append(".gitignore")
    if _append_missing_lines(root / ".gitattributes", [GITATTRIBUTES_LINE]):
        report.created.append(".gitattributes")
    workflow = root / WORKFLOW_PATH
    if not workflow.exists():
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(_workflow_text())
        report.created.append(WORKFLOW_PATH)

    final = load_config(config_path)
    if to_draft:
        report.drafted = draft_modules(root, final, to_draft, client, model, False, now, sleep)
    index_report = run_index(root, final, embedder)
    report.indexed = index_report.indexed
    return report
