from __future__ import annotations

import sys
from pathlib import Path

from repoarena.agents.fake import FakeAgentRunner
from repoarena.benchmark.models import (
    BenchmarkTaskV1,
    CommandSpec,
    QualityReason,
    RunStatus,
    TaskMetadata,
    TaskStatus,
    VerifierSpecV1,
)
from repoarena.benchmark.orchestrator import BenchmarkOrchestrator
from repoarena.benchmark.workspace import PatchValidator
from repoarena.config import RepoArenaPaths
from repoarena.config.models import NetworkPolicy, RepoArenaConfig
from repoarena.sandbox import SandboxExecution
from repoarena.storage import Database
from repoarena.utils.process import run_process
from repoarena.verification.verifier import Verifier


class LocalTestDocker:
    def image_exists(self, image: str) -> bool:
        del image
        return True

    def image_identity(self, image: str) -> str:
        return image

    def pull_image(self, image: str) -> str:
        return image

    def run(
        self,
        *,
        image: str,
        workspace: Path,
        argv: list[str],
        timeout_seconds: int,
        network_policy: NetworkPolicy,
        **kwargs: object,
    ) -> SandboxExecution:
        del image, network_policy, kwargs
        command = [sys.executable if argv[0] == "python" else argv[0], *argv[1:]]
        result = run_process(command, cwd=workspace, timeout=timeout_seconds, check=False)
        return SandboxExecution(result.returncode, result.stdout, result.stderr, 0.01)


class FlakyTestDocker(LocalTestDocker):
    def __init__(self) -> None:
        self.calls = 0

    def run(
        self,
        *,
        image: str,
        workspace: Path,
        argv: list[str],
        timeout_seconds: int,
        network_policy: NetworkPolicy,
        **kwargs: object,
    ) -> SandboxExecution:
        del image, workspace, argv, timeout_seconds, network_policy, kwargs
        self.calls += 1
        return SandboxExecution(1, f"FAILED variant {self.calls}", "", 0.01)


def make_task(fixture: object) -> BenchmarkTaskV1:
    hidden = fixture.git.diff_patch(
        fixture.base, fixture.gold, include_paths=("tests/test_calculator.py",)
    )
    source = fixture.git.diff_patch(
        fixture.base, fixture.gold, exclude_paths=("tests/test_calculator.py",)
    )
    return BenchmarkTaskV1(
        id="fixture-task",
        repository_id=fixture.git.repository_id,
        repository=fixture.git.remote_url,
        base_commit=fixture.base,
        gold_commit=fixture.gold,
        task_description=(
            "The add function returns an incorrect value for two positive integers. "
            "Correct it without changing the public function signature."
        ),
        issue_reference="https://github.com/example/fixture/issues/4",
        pull_request_number=7,
        verification=VerifierSpecV1(
            image="local-test",
            setup_commands=[],
            test_command=CommandSpec(
                argv=["python", "-m", "pytest", "-q", "tests/test_calculator.py"]
            ),
            hidden_test_patch=hidden,
            gold_source_patch=source,
            protected_paths=["tests/test_calculator.py"],
            repetitions=2,
        ),
        metadata=TaskMetadata(
            languages=["Python"],
            quality_score=100,
            quality_reasons=[
                QualityReason(signal="fixture", points=100, detail="Deterministic fixture")
            ],
            files_changed_count=2,
            lines_changed=5,
        ),
        status=TaskStatus.VALID,
    )


def test_provider_free_vertical_slice_records_verified_pass(
    synthetic_repository: object,
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
    task = make_task(fixture)
    database.upsert_task(task)
    config = RepoArenaConfig()
    verifier = Verifier(fixture.git, paths, config, docker=LocalTestDocker())  # type: ignore[arg-type]

    baseline_ok, _ = verifier.validate_baseline(task)
    orchestrator = BenchmarkOrchestrator(
        fixture.git,
        paths,
        database,
        verifier,
        PatchValidator(max_files=50, max_lines=2_000),
    )
    _, completed = orchestrator.run(
        [FakeAgentRunner(task.verification.gold_source_patch)], timeout_seconds=30
    )
    rows = database.report_rows(fixture.git.repository_id)

    assert baseline_ok is True
    assert completed == 1
    assert len(rows) == 1
    assert rows[0]["status"] == RunStatus.PASS.value
    assert rows[0]["verification_status"] == RunStatus.PASS.value
    patch_path = Path(rows[0]["patch_path"])
    assert patch_path.is_file()
    assert "return left + right" in patch_path.read_text(encoding="utf-8")


def _run_fake_agent(fixture: object, patch: str) -> object:
    paths = RepoArenaPaths.for_repository(fixture.path)
    for directory in (paths.state, paths.tasks, paths.runs, paths.reports, paths.cache):
        directory.mkdir(parents=True, exist_ok=True)
    database = Database(paths.database)
    database.migrate()
    database.upsert_repository(
        fixture.git.repository_id, fixture.path, fixture.git.remote_url, "main"
    )
    task = make_task(fixture)
    database.upsert_task(task)
    verifier = Verifier(
        fixture.git,
        paths,
        RepoArenaConfig(),
        docker=LocalTestDocker(),  # type: ignore[arg-type]
    )
    orchestrator = BenchmarkOrchestrator(
        fixture.git,
        paths,
        database,
        verifier,
        PatchValidator(max_files=50, max_lines=2_000),
    )
    orchestrator.run([FakeAgentRunner(patch)], timeout_seconds=30)
    return database.report_rows(fixture.git.repository_id)[0]


def test_no_change_agent_is_not_scored_as_a_test_failure(
    synthetic_repository: object,
) -> None:
    row = _run_fake_agent(synthetic_repository, "")

    assert row["status"] == RunStatus.AGENT_ERROR.value
    assert row["error_type"] == "NO_CHANGE"


def test_wrong_agent_solution_is_scored_as_fail(synthetic_repository: object) -> None:
    wrong_patch = (
        "diff --git a/calculator.py b/calculator.py\n"
        "--- a/calculator.py\n"
        "+++ b/calculator.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(left: int, right: int) -> int:\n"
        "-    return left - right\n"
        "+    return 0\n"
    )
    row = _run_fake_agent(synthetic_repository, wrong_patch)

    assert row["status"] == RunStatus.FAIL.value
    assert row["verification_status"] == RunStatus.FAIL.value


def test_patch_containing_a_credential_is_rejected_without_persistence(
    synthetic_repository: object,
) -> None:
    secret = "sk-" + "abcdefghijklmnop"
    patch = (
        "diff --git a/calculator.py b/calculator.py\n"
        "--- a/calculator.py\n"
        "+++ b/calculator.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def add(left: int, right: int) -> int:\n"
        f"+    # {secret}\n"
        "-    return left - right\n"
        "+    return left + right\n"
    )
    row = _run_fake_agent(synthetic_repository, patch)

    assert row["status"] == RunStatus.INVALID_PATCH.value
    assert row["error_type"] == "SECRET_IN_PATCH"
    assert row["patch_path"] is None
    assert secret not in row["run_stderr"]


def test_flaky_baseline_is_rejected(synthetic_repository: object) -> None:
    fixture = synthetic_repository
    paths = RepoArenaPaths.for_repository(fixture.path)
    paths.cache.mkdir(parents=True, exist_ok=True)
    verifier = Verifier(
        fixture.git,
        paths,
        RepoArenaConfig(),
        docker=FlakyTestDocker(),  # type: ignore[arg-type]
    )

    valid, detail = verifier.validate_baseline(make_task(fixture))

    assert valid is False
    assert detail == "base failure diagnostics were not reproducible"
