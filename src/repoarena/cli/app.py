from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from repoarena import __version__
from repoarena.config import RepoArenaPaths, initialize, load_config
from repoarena.config.manager import find_repository
from repoarena.exceptions import RepoArenaError, RepositoryError
from repoarena.git import GitRepository
from repoarena.storage import Database

app = typer.Typer(
    name="repoarena",
    help="Benchmark AI coding agents on your own repository.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"RepoArena {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True),
) -> None:
    """SWE-bench for your own repository."""


@app.command("init")
def init_command() -> None:
    """Initialize local RepoArena state in the current Git repository."""
    try:
        paths, created = initialize(Path.cwd())
        database = Database(paths.database)
        database.migrate()
        repository = GitRepository(paths.repository)
        try:
            remote = repository.remote_url
        except RepositoryError:
            remote = None
        if remote:
            database.upsert_repository(
                repository.repository_id,
                paths.repository,
                remote,
                repository.default_branch,
            )
    except RepoArenaError as exc:
        console.print(f"[red]Initialization failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    action = "Created" if created else "Validated"
    console.print(f"[green]{action}[/green] {paths.config}")
    console.print(
        f"Repository: {paths.repository} ({repository.default_branch or 'detached/unborn'}, "
        f"{repository.head_commit[:12]})"
    )
    if remote:
        console.print(f"Origin: {remote}")
    else:
        console.print(
            "[yellow]Origin is not configured; GitHub discovery will require it.[/yellow]"
        )
    console.print("Repository and benchmark results stay on this machine.")


def _context() -> tuple[RepoArenaPaths, Database]:
    repository = find_repository(Path.cwd())
    paths = RepoArenaPaths.for_repository(repository)
    load_config(paths)
    database = Database(paths.database)
    database.migrate()
    return paths, database


# Remaining commands are registered after their implementation modules are imported.
from repoarena.cli.commands import register_commands  # noqa: E402

register_commands(app, console, _context)
