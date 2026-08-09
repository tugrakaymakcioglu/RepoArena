from __future__ import annotations

import html
import platform
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from rich.console import Console
from rich.table import Table

from repoarena import __version__
from repoarena.benchmark.models import RunStatus
from repoarena.config import RepoArenaPaths
from repoarena.exceptions import RepoArenaError
from repoarena.git import GitRepository
from repoarena.storage import Database


@dataclass(frozen=True, slots=True)
class AgentSummary:
    agent: str
    passed: int
    runs: int
    average_seconds: float
    task_ids: frozenset[str]
    exact_cost: float | None

    @property
    def pass_rate(self) -> float:
        return self.passed / self.runs if self.runs else 0


def summarize(rows: list[sqlite3.Row]) -> tuple[list[AgentSummary], str | None]:
    latest: dict[tuple[str, str], sqlite3.Row] = {}
    for row in rows:
        latest[(row["agent"], row["task_id"])] = row
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in latest.values():
        groups[row["agent"]].append(row)
    summaries = [
        AgentSummary(
            agent=agent,
            passed=sum(row["status"] == RunStatus.PASS.value for row in agent_rows),
            runs=len(agent_rows),
            average_seconds=sum(float(row["duration_seconds"]) for row in agent_rows)
            / len(agent_rows),
            task_ids=frozenset(str(row["task_id"]) for row in agent_rows),
            exact_cost=_total_exact_cost(agent_rows),
        )
        for agent, agent_rows in sorted(groups.items())
        if agent_rows
    ]
    recommendation = None
    if len(summaries) >= 2 and len({summary.task_ids for summary in summaries}) == 1:
        best_rate = max(summary.pass_rate for summary in summaries)
        winners = [summary.agent for summary in summaries if summary.pass_rate == best_rate]
        if len(winners) == 1:
            recommendation = winners[0]
    return summaries, recommendation


def _total_exact_cost(rows: list[sqlite3.Row]) -> float | None:
    costs: list[float] = []
    for row in rows:
        try:
            value = row["exact_cost"]
        except IndexError:
            return None
        if value is None:
            return None
        costs.append(float(value))
    return sum(costs)


def render_html(
    rows: list[sqlite3.Row],
    summaries: list[AgentSummary],
    recommendation: str | None,
    repository_commit: str,
) -> str:
    generated = datetime.now(UTC).isoformat()
    summary_rows = "".join(
        f"<tr><td>{html.escape(item.agent)}</td><td>{item.pass_rate:.0%}</td>"
        f"<td>{item.average_seconds:.1f}s</td><td>{item.runs}</td>"
        f"<td>{f'${item.exact_cost:.4f}' if item.exact_cost is not None else 'unavailable'}</td></tr>"
        for item in summaries
    )
    detail_rows = "".join(_detail_row(row) for row in rows)
    recommendation_html = (
        f"<p class='recommendation'>Recommended agent: <strong>{html.escape(recommendation)}</strong></p>"
        if recommendation
        else "<p class='muted'>No fair single-agent recommendation is available yet.</p>"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>RepoArena benchmark report</title><style>
:root{{--bg:#0d1117;--panel:#161b22;--text:#e6edf3;--muted:#8b949e;--line:#30363d;--accent:#58a6ff;--pass:#3fb950;--fail:#f85149}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}}
main{{max-width:1100px;margin:0 auto;padding:48px 24px}}h1{{margin-bottom:4px}}.muted{{color:var(--muted)}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:20px;margin:24px 0;overflow:auto}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:10px;border-bottom:1px solid var(--line)}}
th{{color:var(--muted)}}.status.pass{{color:var(--pass)}}.status.fail,.status.agent_error,.status.setup_error{{color:var(--fail)}}
.recommendation{{border-left:3px solid var(--accent);padding:12px 16px;background:var(--panel)}}
details{{max-width:480px}}pre{{white-space:pre-wrap;word-break:break-word;color:var(--muted)}}
</style></head><body><main><h1>RepoArena</h1><p class="muted">Repository-specific coding-agent benchmark</p>
<p class="muted">Generated {html.escape(generated)} · repository commit {html.escape(repository_commit)}</p>
<p class="muted">RepoArena {html.escape(__version__)} · Python {html.escape(platform.python_version())} · {html.escape(platform.platform())}</p>
<section class="card"><h2>Summary</h2><table><thead><tr><th>Agent</th><th>Pass rate</th><th>Avg time</th><th>Runs</th><th>Exact cost</th></tr></thead>
<tbody>{summary_rows}</tbody></table></section>{recommendation_html}
<section class="card"><h2>Task results</h2><table><thead><tr><th>Task</th><th>Agent</th><th>Status</th><th>Time</th><th>Patch</th><th>Cost</th><th>Quality</th><th>Diagnostics</th></tr></thead>
<tbody>{detail_rows}</tbody></table></section></main></body></html>"""


def _row_value(row: sqlite3.Row, key: str, default: object = "") -> Any:
    try:
        return row[key]
    except IndexError:
        return default


def _detail_row(row: sqlite3.Row) -> str:
    diagnostic = "\n".join(
        str(value)
        for value in (
            _row_value(row, "error_type"),
            _row_value(row, "run_stderr"),
            _row_value(row, "test_stdout"),
            _row_value(row, "test_stderr"),
        )
        if value
    )[-4_000:]
    details = (
        "<details><summary>View</summary><pre>" + html.escape(diagnostic) + "</pre></details>"
        if diagnostic
        else ""
    )
    exact_cost = _row_value(row, "exact_cost", None)
    cost = f"${float(exact_cost):.4f}" if exact_cost is not None else "unavailable"
    patch_size = int(_row_value(row, "patch_size", 0))
    files_changed = int(_row_value(row, "files_changed", 0))
    return (
        "<tr>"
        f"<td>{html.escape(str(row['task_id']))}</td>"
        f"<td>{html.escape(str(row['agent']))}</td>"
        f"<td class='status {html.escape(str(row['status']).lower())}'>{html.escape(str(row['status']))}</td>"
        f"<td>{float(row['duration_seconds']):.1f}s</td>"
        f"<td>{patch_size} B / {files_changed} files</td>"
        f"<td>{cost}</td>"
        f"<td>{int(row['quality_score'])}</td>"
        f"<td>{details}</td>"
        "</tr>"
    )


def run_report_command(
    console: Console,
    context: Callable[[], tuple[RepoArenaPaths, Database]],
) -> int:
    try:
        paths, database = context()
        repository = GitRepository(paths.repository)
        rows = database.report_rows(repository.repository_id)
        if not rows:
            raise RepoArenaError("No completed benchmark runs are available.")
        summaries, recommendation = summarize(rows)
        table = Table(title="Benchmark results")
        table.add_column("Agent")
        table.add_column("Pass Rate", justify="right")
        table.add_column("Avg Time", justify="right")
        table.add_column("Runs", justify="right")
        table.add_column("Exact Cost", justify="right")
        for item in summaries:
            table.add_row(
                item.agent,
                f"{item.pass_rate:.0%}",
                f"{item.average_seconds:.1f}s",
                str(item.runs),
                f"${item.exact_cost:.4f}" if item.exact_cost is not None else "unavailable",
            )
        console.print(table)
        if recommendation:
            console.print(
                f"\nRecommended agent for this repository: [bold green]{recommendation}[/bold green]"
            )
        else:
            console.print(
                "\n[yellow]No fair single-agent recommendation is available yet.[/yellow]"
            )
        paths.reports.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = paths.reports / f"report-{stamp}.html"
        output.write_text(
            render_html(rows, summaries, recommendation, repository.head_commit),
            encoding="utf-8",
            newline="\n",
        )
        database.add_report(repository.repository_id, output, repository.head_commit)
    except RepoArenaError as exc:
        console.print(f"[red]Report failed:[/red] {exc}")
        return 1
    console.print(f"HTML report: {output}")
    return 0
