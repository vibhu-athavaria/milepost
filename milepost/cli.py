"""Typer app. Command wiring only: parse input, call a service, format output."""

import functools
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import typer

from milepost.config import Config, Index, load_config, load_config_or_default, resolve_model
from milepost.embeddings import Embedder, default_embedder
from milepost.env import is_disabled, load_env
from milepost.errors import EnvironmentProblem, MilepostError, UsageError
from milepost.llm.client import LiteLlmClient, LlmClient
from milepost.mcp_server import run_server
from milepost.services.check import run_check
from milepost.services.coverage import CONFIG_NAME, undeclared_candidates
from milepost.services.doctor import run_doctor
from milepost.services.draft import draft_modules
from milepost.services.hook import post_edit as hook_post_edit_text
from milepost.services.hook import project_root as hook_project_root
from milepost.services.hook import session_start as hook_session_start_text
from milepost.services.hook import stop as hook_stop_text
from milepost.services.hooks import install_hooks, uninstall_hooks
from milepost.services.impact import file_impact
from milepost.services.index import run_index
from milepost.services.init import InitReport, run_init
from milepost.services.merge_driver import run_merge_driver
from milepost.services.outline import outline_file
from milepost.services.render import render_index
from milepost.services.report import build_report, render_markdown, report_as_dict
from milepost.services.review import review_note
from milepost.services.search import search as run_search
from milepost.services.status import module_statuses
from milepost.services.sync import sync as run_sync
from milepost.services.uninstall import run_uninstall

app = typer.Typer(
    help="Git-native, drift-checked codebase memory for coding agents.",
    no_args_is_help=True,
)
hooks_app = typer.Typer(help="Manage git hooks and the merge driver.", no_args_is_help=True)
hook_app = typer.Typer(
    help="Entry points called by the Claude Code plugin hooks.",
    no_args_is_help=True,
)
app.add_typer(hooks_app, name="hooks")
app.add_typer(hook_app, name="hook")


RepoOption = Annotated[
    Path | None,
    typer.Option("--repo", help="Repository root (default: nearest ancestor with milepost.toml)."),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]


def handle_errors[**P](func: Callable[P, None]) -> Callable[P, None]:
    """Turn a MilepostError into a message on stderr and the error's exit code."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            func(*args, **kwargs)
        except MilepostError as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(code=error.exit_code) from error

    return wrapper


def _embedder(config: Config) -> Embedder | None:
    return default_embedder(config.index.embedding_model, config.index.embedding_dim)


def _embedder_for(root: Path) -> Embedder | None:
    """Embedder for init, which may run before milepost.toml exists: use the default model."""
    config_path = root / CONFIG_NAME
    index = load_config(config_path).index if config_path.is_file() else Index()
    return default_embedder(index.embedding_model, index.embedding_dim)


def _llm_client() -> LlmClient:
    return LiteLlmClient()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo_root(repo: Path | None) -> Path:
    if repo is not None:
        return repo
    start = Path.cwd()
    for directory in (start, *start.parents):
        if (directory / CONFIG_NAME).is_file():
            return directory
    return start


def _print_version(show: bool) -> None:
    if show:
        typer.echo(version("milepost"))
        raise typer.Exit()


@app.callback()
def main(
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Print the version.",
        ),
    ] = False,
) -> None:
    """Git-native, drift-checked codebase memory for coding agents."""


@app.command()
@handle_errors
def init(
    repo: RepoOption = None,
    modules: Annotated[
        str | None, typer.Option("--modules", help="Comma-separated candidate ids to declare.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List what would be sent; write nothing.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
    force_config: Annotated[
        bool, typer.Option("--force-config", help="Replace an existing milepost.toml.")
    ] = False,
    no_hooks: Annotated[bool, typer.Option("--no-hooks", help="Do not install git hooks.")] = False,
    model_mode: Annotated[
        bool,
        typer.Option(
            "--model-mode",
            help="Draft notes with a separate model (needs the model extra and MILEPOST_MODEL) "
            "instead of your coding agent.",
        ),
    ] = False,
) -> None:
    """Scaffold the knowledge base, declare modules, and draft their notes."""
    root = _repo_root(repo)
    load_env(root)
    wanted = [m.strip() for m in modules.split(",") if m.strip()] if modules else None

    def run(dry: bool) -> InitReport:
        return run_init(
            root,
            modules=wanted,
            dry_run=dry,
            force_config=force_config,
            client=_llm_client(),
            embedder=_embedder_for(root),
            environ=os.environ,
            now=_now(),
            sleep=time.sleep,
            install_hooks_flag=not no_hooks,
            model_mode=model_mode,
        )

    if dry_run or not yes:
        plan = run(True)
        verb = "show your coding agent" if plan.agent_mode else "send"
        for module_id, files in plan.planned_files.items():
            typer.echo(f"{module_id}: would {verb} {len(files)} file(s)")
            for path in files:
                typer.echo(f"  {path}")
        for module_id, outlined in plan.outline_only.items():
            typer.echo(
                f"warning: {module_id}: {len(outlined)} file(s) exceed draft.max_source_bytes and "
                "would be sent as outline only; raise it in milepost.toml to cover them"
            )
        for module_id, held in plan.withheld.items():
            typer.echo(
                f"warning: {module_id}: {', '.join(held)} look like they contain a credential and "
                "would be left out; if they are safe, list them in draft.secret_scan_allow"
            )
        typer.echo(f"estimated tokens: {plan.estimated_tokens}")
        if dry_run:
            return
        if not sys.stdin.isatty():
            raise UsageError("not an interactive shell; rerun with --yes to confirm")
        question = (
            "Set up milepost and let your coding agent draft the notes?"
            if plan.agent_mode
            else "Send these files to the configured model and write the notes?"
        )
        if not typer.confirm(question):
            raise typer.Exit(code=1)
    report = run(False)
    for path in report.created:
        typer.echo(f"created {path}")
    if report.hooks is not None:
        if report.hooks.written:
            typer.echo(f"installed git hooks: {', '.join(report.hooks.written)}")
        else:
            typer.echo(f"git hooks not installed: {report.hooks.skipped_reason}")
            typer.echo(report.hooks.snippet)
    for module_id in report.drafted:
        typer.echo(f"drafted kb/modules/{module_id}.md (status: draft)")
    if report.agent_pending:
        typer.echo(
            "draft.mode = agent: no notes were written. Ask your coding agent to call "
            "kb_draft_module for each of: " + ", ".join(report.agent_pending)
        )
        typer.echo(
            "Next: when it has written them, read each draft and run `milepost review <id>` "
            "for each one that is right, then commit."
        )
    if report.drafted:
        typer.echo(
            "Next: read each draft, run `milepost review <id>` for each one that is right, "
            "then commit milepost.toml, kb/, .gitignore, .gitattributes and the CI workflow."
        )
    elif not report.declared:
        typer.echo(
            "No modules declared. Run `milepost scan`, then `milepost init --modules <ids>`."
        )


@app.command()
@handle_errors
def check(
    repo: RepoOption = None,
    ci: Annotated[bool, typer.Option("--ci", help="Scope failures to the change range.")] = False,
    base: Annotated[str | None, typer.Option("--base", help="Base git ref for --ci.")] = None,
    output_format: Annotated[str, typer.Option("--format", help="text or json.")] = "text",
    no_churn: Annotated[
        bool,
        typer.Option(
            "--no-churn", help="Skip the slower unreviewed-churn warning (used by hooks)."
        ),
    ] = False,
) -> None:
    """Validate notes and detect stale ones."""
    if output_format not in ("text", "json"):
        raise UsageError(f"--format must be 'text' or 'json', got '{output_format}'")
    if ci and base is None:
        raise UsageError("--ci requires --base <ref>")
    root = _repo_root(repo)
    config = load_config(root / CONFIG_NAME)
    result = run_check(root, config, base if ci else None, with_churn=not no_churn)
    if output_format == "json":
        payload = [
            {"severity": f.severity, "code": f.code, "path": f.path, "message": f.message}
            for f in result.findings
        ]
        typer.echo(json.dumps(payload, indent=2))
    else:
        for finding in result.findings:
            typer.echo(f"{finding.severity} {finding.code} {finding.path}: {finding.message}")
        failures = sum(1 for f in result.findings if f.severity == "failure")
        warnings = len(result.findings) - failures
        typer.echo(f"{failures} failure(s), {warnings} warning(s)")
        if result.exit_code:
            typer.echo("Next: update each failing note, then rerun `milepost check`.")
    if result.exit_code:
        raise typer.Exit(code=result.exit_code)


@app.command()
@handle_errors
def overview(repo: RepoOption = None) -> None:
    """Print the module index (one line per module), built from the notes."""
    root = _repo_root(repo)
    typer.echo(render_index(root, load_config(root / CONFIG_NAME)), nl=False)


@app.command()
@handle_errors
def index(
    repo: RepoOption = None,
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Drop and rebuild everything.")
    ] = False,
) -> None:
    """Build or update the local search index."""
    root = _repo_root(repo)
    config = load_config(root / CONFIG_NAME)
    report = run_index(root, config, _embedder(config), rebuild=rebuild)
    for path in report.skipped_invalid:
        typer.echo(f"warning: skipped invalid note {path}", err=True)
    typer.echo(f"indexed {report.indexed}, skipped {report.skipped}, removed {report.removed}")


@app.command()
@handle_errors
def draft(
    module_id: Annotated[str, typer.Argument(help="Module id to draft.")],
    repo: RepoOption = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite a reviewed note.")] = False,
) -> None:
    """Draft one module's L2 note (status: draft)."""
    root = _repo_root(repo)
    load_env(root)
    config = load_config(root / CONFIG_NAME)
    if config.draft.mode == "agent":
        raise UsageError(
            'draft.mode is "agent": ask your coding agent to call kb_draft_module '
            f"{module_id} instead (this command needs a model)"
        )
    model = resolve_model(config, os.environ)
    draft_modules(root, config, [module_id], _llm_client(), model, force, _now(), time.sleep)
    typer.echo(f"drafted kb/modules/{module_id}.md (status: draft)")
    typer.echo(f"Next: read it, then run `milepost review {module_id}` if it is right.")


@app.command()
@handle_errors
def review(
    note_id: Annotated[str, typer.Argument(help="Note id, for example module/services.")],
    repo: RepoOption = None,
) -> None:
    """Mark a note as reviewed by you, after you have read it."""
    root = _repo_root(repo)
    config = load_config(root / CONFIG_NAME)
    review_note(root, config, note_id, _now())
    typer.echo(f"{note_id} marked reviewed")
    typer.echo("Next: commit the note.")


@app.command()
@handle_errors
def search(
    query: Annotated[str, typer.Argument(help="What to look for.")],
    repo: RepoOption = None,
    k: Annotated[int, typer.Option("--k", help="Number of results.")] = 5,
    json_output: JsonOption = False,
) -> None:
    """Search the notes."""
    root = _repo_root(repo)
    config = load_config(root / CONFIG_NAME)
    results = run_search(root, config, _embedder(config), query, k=k)
    if json_output:
        typer.echo(json.dumps([asdict(result) for result in results], indent=2))
        return
    for result in results:
        snippet = " ".join(result.snippet.split())[:100]
        typer.echo(f"{result.score:.4f}  {result.note_id}  [{result.heading}]  {snippet}")


@app.command()
@handle_errors
def outline(
    path: Annotated[str, typer.Argument(help="Source file, relative to the repo root.")],
    repo: RepoOption = None,
    json_output: JsonOption = False,
) -> None:
    """List the symbols of one file with line ranges, computed now."""
    result = outline_file(_repo_root(repo), path)
    if json_output:
        typer.echo(json.dumps(asdict(result), indent=2))
        return
    typer.echo(f"{result.path} ({result.line_count} lines)")
    for symbol in result.symbols:
        doc = f"  # {symbol.doc}" if symbol.doc else ""
        typer.echo(f"{symbol.start_line}-{symbol.end_line}  {symbol.kind}  {symbol.signature}{doc}")
    if result.truncated:
        typer.echo("(truncated: more symbols than the limit; read the file for the rest)")


@app.command()
@handle_errors
def impact(
    path: Annotated[str, typer.Argument(help="Source file, relative to the repo root.")],
    repo: RepoOption = None,
    json_output: JsonOption = False,
) -> None:
    """List who imports a file and which tests likely cover it, computed now."""
    root = _repo_root(repo)
    result = file_impact(root, load_config_or_default(root / CONFIG_NAME), path)
    if json_output:
        typer.echo(json.dumps(asdict(result), indent=2))
        return
    typer.echo(f"{result.path}")
    typer.echo(f"importers ({len(result.importers)}):")
    for importer in result.importers:
        typer.echo(f"  {importer}")
    typer.echo(f"tests ({len(result.tests)}):")
    for test in result.tests:
        typer.echo(f"  {test.path}  (via {test.via})")
    for module in result.modules:
        typer.echo(f"module {module.id}: " + (", ".join(module.verify) or "no verify commands"))
    if result.notes:
        typer.echo("notes: " + ", ".join(result.notes))
    if result.truncated:
        typer.echo("(truncated at the list limit)")
    typer.echo(f"note: {result.caveat}")


@app.command()
@handle_errors
def sync(
    repo: RepoOption = None,
    base: Annotated[
        str | None, typer.Option("--base", help="Compare REF...HEAD instead of the working tree.")
    ] = None,
    json_output: JsonOption = False,
) -> None:
    """Show what changed and which notes to update, and how."""
    root = _repo_root(repo)
    result = run_sync(root, load_config_or_default(root / CONFIG_NAME), base)
    if json_output:
        typer.echo(json.dumps(asdict(result), indent=2))
        return
    for change in result.changes:
        typer.echo(f"{change.status:<8} {change.path}")
        for route in change.routes:
            typer.echo(f"  - {route}")
    typer.echo("Next:")
    for step in result.next_steps:
        typer.echo(f"  - {step}")


@app.command()
@handle_errors
def status(repo: RepoOption = None, json_output: JsonOption = False) -> None:
    """Show, per module, how far the code has moved since a person last reviewed its note."""
    root = _repo_root(repo)
    statuses = module_statuses(root, load_config(root / CONFIG_NAME))
    if json_output:
        typer.echo(json.dumps([asdict(s) for s in statuses], indent=2))
        return
    typer.echo(f"{'module':<20} {'note':<9} {'lines':>6} {'commits':>7} {'agent':>5}  reviewed by")
    for entry in statuses:
        if entry.never_reviewed:
            typer.echo(f"{entry.module_id:<20} {entry.note_status:<9} {'never reviewed':>21}")
            continue
        typer.echo(
            f"{entry.module_id:<20} {entry.note_status:<9} {entry.lines_changed_since:>6} "
            f"{entry.commits_since:>7} {entry.agent_commits_since:>5}  "
            f"{entry.reviewed_by} {entry.reviewed_at}"
        )


@app.command()
@handle_errors
def report(
    base: Annotated[str, typer.Option("--base", help="Base git ref, e.g. origin/main.")],
    repo: RepoOption = None,
    output_format: Annotated[str, typer.Option("--format", help="markdown or json.")] = "markdown",
) -> None:
    """Summarise a change range for a reviewer: what to look at first. Always exits 0."""
    if output_format not in ("markdown", "json"):
        raise UsageError(f"--format must be 'markdown' or 'json', got '{output_format}'")
    root = _repo_root(repo)
    try:
        built = build_report(root, load_config(root / CONFIG_NAME), base)
    except MilepostError as error:
        # A review aid must never fail a pull request: say what went wrong and exit 0.
        message = f"Report unavailable: {error}"
        typer.echo(json.dumps({"error": message}) if output_format == "json" else message)
        return
    if output_format == "json":
        typer.echo(json.dumps(report_as_dict(built), indent=2))
    else:
        typer.echo(render_markdown(built))


@app.command(name="merge-driver")
def merge_driver(
    base: Annotated[Path, typer.Argument(help="%O: the common ancestor version.")],
    ours: Annotated[Path, typer.Argument(help="%A: our version; the result is written here.")],
    theirs: Annotated[Path, typer.Argument(help="%B: their version.")],
    name: Annotated[str, typer.Argument(help="%P: the path of the file being merged.")],
) -> None:
    """Git merge driver for kb notes."""
    code = run_merge_driver(base, ours, theirs, name)
    if code:
        raise typer.Exit(code=code)


@app.command()
@handle_errors
def serve(repo: RepoOption = None) -> None:
    """Run the MCP server on stdio."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    root = repo or (Path(project_dir) if project_dir else _repo_root(None))
    load_env(root)
    run_server(root)


@app.command()
def doctor(repo: RepoOption = None, json_output: JsonOption = False) -> None:
    """Report the environment milepost needs."""
    root = _repo_root(repo)
    load_env(root)
    report = run_doctor(root, os.environ)
    if json_output:
        payload = [{"name": c.name, "status": c.status, "detail": c.detail} for c in report.checks]
        typer.echo(json.dumps({"ok": report.exit_code == 0, "checks": payload}, indent=2))
    else:
        for check in report.checks:
            typer.echo(f"{check.status:<4} {check.name}: {check.detail}")
    if report.exit_code:
        raise typer.Exit(code=report.exit_code)


@app.command()
@handle_errors
def scan(repo: RepoOption = None, json_output: JsonOption = False) -> None:
    """List candidate modules that are not yet declared."""
    candidates = undeclared_candidates(_repo_root(repo))
    if json_output:
        payload = [{"id": c.id, "path": c.path, "sources": c.sources} for c in candidates]
        typer.echo(json.dumps({"candidates": payload}, indent=2))
        return
    for candidate in candidates:
        typer.echo(f"{candidate.id}\t{candidate.path}\t{', '.join(candidate.sources)}")


@hooks_app.command("install")
@handle_errors
def hooks_install(repo: RepoOption = None) -> None:
    """Install git hooks and the merge driver."""
    report = install_hooks(_repo_root(repo))
    if report.written:
        typer.echo(f"installed git hooks: {', '.join(report.written)}")
        typer.echo("merge driver configured; commit .gitattributes")
        return
    typer.echo(f"git hooks not installed: {report.skipped_reason}")
    typer.echo(report.snippet)


@app.command()
@handle_errors
def uninstall(
    repo: RepoOption = None,
    delete_notes: Annotated[
        bool, typer.Option("--delete-notes", help="Also delete the notes under kb/")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", help="Do it; without this only list")] = False,
) -> None:
    """Remove what milepost added to this repository (lists first; --yes to apply)."""
    root = _repo_root(repo)
    report = run_uninstall(root, delete_notes, apply=yes)
    if report.failed:
        for line in report.done:
            typer.echo(f"removed: {line}")
        raise EnvironmentProblem(
            f"stopped at {report.failed}. Already removed: {', '.join(report.done) or 'nothing'}. "
            "Fix the cause and run again; finished steps are skipped."
        )
    verb = "removed" if report.applied else "would remove"
    for line in report.remove:
        typer.echo(f"{verb}: {line}")
    for line in report.keep:
        typer.echo(f"kept: {line}")
    if not report.remove:
        typer.echo("nothing to remove: milepost is not set up here")
    for line in report.manual:
        typer.echo(f"by hand: {line}")
    if report.blocked:
        if yes:
            raise UsageError(report.blocked)
        typer.echo(f"blocked: {report.blocked}")
    if report.remove and not report.applied:
        typer.echo("nothing was changed; run again with --yes to do this")
    elif report.applied:
        typer.echo("review with `git status`; undo with `git restore .` (tracked files)")


@hooks_app.command("uninstall")
@handle_errors
def hooks_uninstall(repo: RepoOption = None) -> None:
    """Remove hooks installed by milepost."""
    removed = uninstall_hooks(_repo_root(repo))
    typer.echo(f"removed: {', '.join(removed)}" if removed else "no milepost hooks found")


def _hook_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _run_hook(handler: Callable[[Path, dict[str, Any]], str]) -> None:
    """Hooks always exit 0: any failure prints a warning on stderr and adds no context."""
    if is_disabled():
        return
    try:
        payload = _hook_payload()
        output = handler(hook_project_root(payload, os.environ.get("CLAUDE_PROJECT_DIR")), payload)
    except Exception as error:  # noqa: BLE001 - a hook must never block the agent
        typer.echo(f"milepost hook: {error}", err=True)
        return
    if output:
        typer.echo(output)


@hook_app.command("session-start")
def hook_session_start() -> None:
    """Add the index to the session context."""
    _run_hook(lambda root, payload: hook_session_start_text(root))


@hook_app.command("post-edit")
def hook_post_edit() -> None:
    """List the notes covering an edited file."""
    _run_hook(hook_post_edit_text)


@hook_app.command("stop")
def hook_stop() -> None:
    """Run the check when the agent tries to finish."""
    _run_hook(hook_stop_text)
