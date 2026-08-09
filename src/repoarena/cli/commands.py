from __future__ import annotations

from collections.abc import Callable

import typer
from rich.console import Console

from repoarena.config.manager import RepoArenaPaths
from repoarena.storage import Database


def register_commands(
    app: typer.Typer,
    console: Console,
    context: Callable[[], tuple[RepoArenaPaths, Database]],
) -> None:
    """Register commands without making the CLI module import every subsystem eagerly."""

    @app.command()
    def doctor() -> None:
        """Check repository, Docker, GitHub, and agent readiness."""
        from repoarena.doctor import run_doctor

        raise typer.Exit(code=run_doctor(console, context))

    @app.command()
    def discover(
        limit: int | None = typer.Option(None, min=1, help="Limit merged PRs inspected."),
    ) -> None:
        """Discover and validate historical benchmark tasks."""
        from repoarena.discovery.service import run_discovery_command

        raise typer.Exit(code=run_discovery_command(console, context, limit=limit))

    @app.command()
    def benchmark(
        agent: str | None = typer.Option(None, help="Configured agent name."),
        all_agents: bool = typer.Option(False, "--all", help="Run every enabled agent."),
    ) -> None:
        """Run a fair benchmark against valid discovered tasks."""
        from repoarena.benchmark.orchestrator import run_benchmark_command

        if (agent is None) == (not all_agents):
            console.print("[red]Choose exactly one of --agent NAME or --all.[/red]")
            raise typer.Exit(code=2)
        raise typer.Exit(
            code=run_benchmark_command(console, context, agent=agent, all_agents=all_agents)
        )

    @app.command()
    def report() -> None:
        """Print results and generate a self-contained HTML report."""
        from repoarena.report.generator import run_report_command

        raise typer.Exit(code=run_report_command(console, context))
