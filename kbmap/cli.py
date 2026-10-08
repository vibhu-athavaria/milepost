"""Typer app. Command wiring only: parse input, call a service, format output."""

import functools
import json
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from kbmap.config import load_config
from kbmap.errors import KbmapError, UsageError
from kbmap.services.check import run_check
from kbmap.services.coverage import CONFIG_NAME, undeclared_candidates

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
    typer.Option("--repo", help="Repository root (default: nearest ancestor with kbmap.toml)."),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]


def handle_errors[**P](func: Callable[P, None]) -> Callable[P, None]:
    """Turn a KbmapError into a message on stderr and the error's exit code."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            func(*args, **kwargs)
        except KbmapError as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(code=error.exit_code) from error

    return wrapper


def _repo_root(repo: Path | None) -> Path:
    if repo is not None:
        return repo
    start = Path.cwd()
    for directory in (start, *start.parents):
        if (directory / CONFIG_NAME).is_file():
            return directory
    return start


def _not_implemented(command: str) -> NoReturn:
    typer.echo(f"kbmap {command} is not implemented yet.", err=True)
    raise typer.Exit(code=1)


def _print_version(show: bool) -> None:
    if show:
        typer.echo(version("kbmap"))
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
                "Next: update each stale note (kb_update, or `kbmap rehash <id>` after review), "
                "then rerun `kbmap check`."
            )
    if result.exit_code:
        raise typer.Exit(code=result.exit_code)


@app.command()
def index() -> None:
    """Build or update the local search index."""
    _not_implemented("index")


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
def search() -> None:
    """Search the notes."""
    _not_implemented("search")


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
    """Report the environment kbmap needs."""
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
    """Remove hooks installed by kbmap."""
    _not_implemented("hooks uninstall")


@hook_app.command("post-edit")
def hook_post_edit() -> None:
    """List the notes covering an edited file."""
    _not_implemented("hook post-edit")


@hook_app.command("stop")
def hook_stop() -> None:
    """Run the check when the agent tries to finish."""
    _not_implemented("hook stop")
