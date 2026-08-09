from __future__ import annotations

from pathlib import Path

from repoarena.benchmark.models import TaskStatus
from repoarena.config import RepoArenaPaths
from repoarena.config.models import RepoArenaConfig
from repoarena.discovery.github import MetadataSource
from repoarena.discovery.models import IssueMetadata, PullRequestMetadata
from repoarena.discovery.service import DiscoveryService
from repoarena.storage import Database


class FixtureMetadata(MetadataSource):
    def __init__(self, gold: str) -> None:
        self.gold = gold

    def merged_pull_requests(self, *, limit: int | None = None) -> list[PullRequestMetadata]:
        del limit
        return [
            PullRequestMetadata(
                number=7,
                title="Fix calculator addition",
                body="Fixes #4",
                url="https://github.com/example/fixture/pull/7",
                merge_commit=self.gold,
                merged_at="2026-01-01T00:00:00Z",
                issue=IssueMetadata(
                    number=4,
                    title="Calculator subtracts instead of adding",
                    body=(
                        "Calling add with two positive integers returns the wrong value. "
                        "Correct calculator.py for #99 and preserve the public function signature."
                    ),
                    url="https://github.com/example/fixture/issues/4",
                ),
                ci_success=True,
            )
        ]


def test_discovery_separates_solver_and_verifier_data(
    synthetic_repository: object, tmp_path: Path
) -> None:
    fixture = synthetic_repository
    paths = RepoArenaPaths.for_repository(fixture.path)
    for directory in (paths.state, paths.tasks, paths.runs, paths.reports, paths.cache):
        directory.mkdir(parents=True, exist_ok=True)
    database = Database(paths.database)
    database.migrate()
    database.upsert_repository(
        fixture.git.repository_id, fixture.path, fixture.git.remote_url, "main"
    )
    service = DiscoveryService(
        fixture.git,
        paths,
        RepoArenaConfig(),
        database,
        FixtureMetadata(fixture.gold),
        lambda task: (True, "fixture baseline"),
    )

    stats = service.discover()
    tasks = database.list_tasks(fixture.git.repository_id)

    assert stats.valid_tasks == 1
    assert len(tasks) == 1
    task = tasks[0]
    assert task.status is TaskStatus.VALID
    assert "test_calculator.py" in task.verification.hidden_test_patch
    assert "return left + right" in task.verification.gold_source_patch
    solver_dump = {
        "schema_version": "1",
        "id": task.id,
        "task_description": task.task_description,
        "languages": task.metadata.languages,
    }
    serialized = str(solver_dump)
    assert fixture.gold not in serialized
    assert "github.com" not in serialized
    assert "test_calculator.py" not in serialized
    assert "calculator.py" not in task.task_description
    assert "#99" not in task.task_description
