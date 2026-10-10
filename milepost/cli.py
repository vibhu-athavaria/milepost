"""Typer app. Command wiring only: parse input, call a service, format output."""

import functools
import json
from collections.abc import Callable
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from milepost.config import Config, load_config
from milepost.embeddings import FastembedEmbedder
from milepost.errors import MilepostError, UsageError
from milepost.services.check import run_check
from milepost.services.coverage import CONFIG_NAME, undeclared_candidates
from milepost.services.index import run_index
from milepost.services.search import search as run_search

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


def _embedder(config: Config) -> FastembedEmbedder:
    return FastembedEmbedder(config.index.embedding_model, config.index.embedding_dim)


def _repo_root(repo: Path | None) -> Path:
    if repo is not None:
        return repo
    start = Path.cwd()
    for directory in (start, *start.parents):
        if (directory / CONFIG_NAME).is_file():
            return directory
    return start


def _not_implemented(command: str) -> NoReturn:
    typer.echo(f"milepost {command} is not implemented yet.", err=True)
    raise typer.Exit(code=1)


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
def init() -> None:
    """Scaffold the knowledge base and draft module notes."""
    _not_implemented("init")


@app.command()
@handle_errors
def check(
    repo: RepoOption = None,
    ci: Annotated[bool, typer.Option("--ci", help="Scope failures to the change range.")] = False,
    base: Annotated[str | None, typer.Option("--base", help="Base git ref for --ci.")] = None,
    output_format: Annotated[str, typer.Option("--format", help="text or json.")] = "text",
) -> None:
    """Validate notes and detect stale ones."""
    if output_format not in ("text", "json"):
        raise UsageError(f"--format must be 'text' or 'json', got '{output_format}'")
    if ci and base is None:
        raise UsageError("--ci requires --base <ref>")
    root = _repo_root(repo)
    config = load_config(root / CONFIG_NAME)
    result = run_check(root, config, base if ci else None)
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
            typer.echo(
                "Next: update each stale note (kb_update, or `milepost rehash <id>` after review), "
                "then rerun `milepost check`."
            )
    if result.exit_code:
        raise typer.Exit(code=result.exit_code)


@app.command()
@handle_errors
def index(
    repo: RepoOption = None,
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Drop and rebuild everything.")
    ] = False,
) -> None:
    """Write INDEX.md and build or update the local search index."""
    root = _repo_root(repo)
    config = load_config(root / CONFIG_NAME)
    report = run_index(root, config, _embedder(config), rebuild=rebuild)
    for path in report.skipped_invalid:
        typer.echo(f"warning: skipped invalid note {path}", err=True)
    typer.echo(f"indexed {report.indexed}, skipped {report.skipped}, removed {report.removed}")


@app.command()
def draft() -> None:
    """Draft a module or file note."""
    _not_implemented("draft")


@app.command()
def review() -> None:
    """Mark a draft note as reviewed."""
    _not_implemented("review")


@app.command()
def rehash() -> None:
    """Recompute the source hash of a note after review."""
    _not_implemented("rehash")


@app.command()
@handle_errors
def search(
    query: Annotated[str, typer.Argument(help="What to look for.")],
    repo: RepoOption = None,
    level: Annotated[str | None, typer.Option("--level", help="Only L1, L2, L3 or L4.")] = None,
    k: Annotated[int, typer.Option("--k", help="Number of results.")] = 5,
    json_output: JsonOption = False,
) -> None:
    """Search the notes."""
    root = _repo_root(repo)
    config = load_config(root / CONFIG_NAME)
    results = run_search(root, config, _embedder(config), query, level=level, k=k)
    if json_output:
        typer.echo(json.dumps([asdict(result) for result in results], indent=2))
        return
    for result in results:
        snippet = " ".join(result.snippet.split())[:100]
        typer.echo(f"{result.score:.4f}  {result.note_id}  [{result.heading}]  {snippet}")


@app.command(name="merge-driver")
def merge_driver() -> None:
    """Git merge driver for kb notes."""
    _not_implemented("merge-driver")


@app.command()
def serve() -> None:
    """Run the MCP server on stdio."""
    _not_implemented("serve")


@app.command()
def doctor() -> None:
    """Report the environment milepost needs."""
    _not_implemented("doctor")


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
def hooks_install() -> None:
    """Install git hooks and the merge driver."""
    _not_implemented("hooks install")


@hooks_app.command("uninstall")
def hooks_uninstall() -> None:
    """Remove hooks installed by milepost."""
    _not_implemented("hooks uninstall")


@hook_app.command("post-edit")
def hook_post_edit() -> None:
    """List the notes covering an edited file."""
    _not_implemented("hook post-edit")


@hook_app.command("stop")
def hook_stop() -> None:
    """Run the check when the agent tries to finish."""
    _not_implemented("hook stop")
