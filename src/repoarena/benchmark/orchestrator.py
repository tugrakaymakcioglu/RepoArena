from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Sequence

from rich.console import Console

from repoarena.agents.base import AgentRunner
from repoarena.agents.registry import select_agents
from repoarena.benchmark.models import AgentContext, RunStatus, SolverTaskV1
from repoarena.benchmark.workspace import PatchValidator, WorkspaceFactory, capture_patch
from repoarena.config import RepoArenaPaths, load_config
from repoarena.exceptions import RepoArenaError
from repoarena.git import GitRepository
from repoarena.sandbox import DockerRunner
from repoarena.storage import Database
from repoarena.utils.redaction import redact
from repoarena.verification.verifier import Verifier


class BenchmarkOrchestrator:
    def __init__(
        self,
        repository: GitRepository,
        paths: RepoArenaPaths,
        database: Database,
        verifier: Verifier,
        patch_validator: PatchValidator,
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.database = database
        self.verifier = verifier
        self.patch_validator = patch_validator

    def run(self, agents: Sequence[AgentRunner], *, timeout_seconds: int) -> tuple[str, int]:
        tasks = self.database.list_tasks(self.repository.repository_id)
        if not tasks:
            raise RepoArenaError("No valid tasks. Run `repoarena discover` first.")
        names = [agent.name for agent in agents]
        task_definitions: list[dict[str, object]] = []
        for task in tasks:
            definition = task.model_dump(mode="json")
            metadata = definition.get("metadata")
            if isinstance(metadata, dict):
                metadata.pop("discovered_at", None)
            task_definitions.append(definition)
        snapshot = json.dumps(
            task_definitions,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        task_hash = hashlib.sha256(snapshot.encode()).hexdigest()
        self.database.recover_interrupted_sessions(self.repository.repository_id)
        session_id = self.database.create_session(self.repository.repository_id, task_hash, names)
        completed = 0
        try:
            for agent in agents:
                errors = agent.validate_environment()
                if errors:
                    raise RepoArenaError(f"{agent.name} is not ready: {'; '.join(errors)}")
                for task in tasks:
                    source = self.repository.source_with_commits(
                        [task.base_commit], self.paths.cache
                    )
                    factory = WorkspaceFactory(source)
                    agent_id = self.database.upsert_agent(agent.name, None, None)
                    run_id = self.database.create_run(session_id, task.id, agent_id)
                    solver_task = SolverTaskV1(
                        id=task.id,
                        task_description=task.task_description,
                        languages=task.metadata.languages,
                    )
                    started = time.monotonic()
                    try:
                        with factory.materialize(task.base_commit, solver=True) as workspace:
                            context = AgentContext(
                                workspace=str(workspace),
                                timeout_seconds=timeout_seconds,
                                run_id=run_id,
                            )
                            agent.prepare(context)
                            try:
                                agent_result = agent.run(context, solver_task)
                            finally:
                                agent.cleanup()
                            self.database.upsert_agent(
                                agent.name, agent_result.version, agent_result.model
                            )
                            if agent_result.status is not RunStatus.PASS:
                                self.database.finish_run(
                                    run_id,
                                    status=agent_result.status,
                                    duration_seconds=time.monotonic() - started,
                                    patch_size=0,
                                    files_changed=0,
                                    stdout=redact(agent_result.stdout),
                                    stderr=redact(agent_result.stderr),
                                    error_type=agent_result.status.value,
                                    exact_cost=agent_result.exact_cost,
                                )
                                completed += 1
                                continue
                            patch = capture_patch(workspace)
                    except RepoArenaError as exc:
                        self.database.finish_run(
                            run_id,
                            status=RunStatus.AGENT_ERROR,
                            duration_seconds=time.monotonic() - started,
                            patch_size=0,
                            files_changed=0,
                            stdout="",
                            stderr=redact(str(exc)),
                            error_type=type(exc).__name__,
                            exact_cost=None,
                        )
                        completed += 1
                        continue
                    if not patch.strip():
                        self.database.finish_run(
                            run_id,
                            status=RunStatus.AGENT_ERROR,
                            duration_seconds=time.monotonic() - started,
                            patch_size=0,
                            files_changed=0,
                            stdout=redact(agent_result.stdout),
                            stderr="Agent completed without changing the repository.",
                            error_type="NO_CHANGE",
                            exact_cost=agent_result.exact_cost,
                        )
                        completed += 1
                        continue
                    secrets = [
                        value
                        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN")
                        if (value := os.environ.get(name))
                    ]
                    if redact(patch, secrets) != patch:
                        self.database.finish_run(
                            run_id,
                            status=RunStatus.INVALID_PATCH,
                            duration_seconds=time.monotonic() - started,
                            patch_size=len(patch.encode()),
                            files_changed=0,
                            stdout=redact(agent_result.stdout),
                            stderr="Patch appears to contain a credential and was not persisted.",
                            error_type="SECRET_IN_PATCH",
                            exact_cost=agent_result.exact_cost,
                        )
                        completed += 1
                        continue
                    try:
                        inspection = self.patch_validator.inspect(
                            patch, protected_paths=tuple(task.verification.protected_paths)
                        )
                    except RepoArenaError as exc:
                        self.database.finish_run(
                            run_id,
                            status=RunStatus.INVALID_PATCH,
                            duration_seconds=time.monotonic() - started,
                            patch_size=len(patch.encode()),
                            files_changed=0,
                            stdout=redact(agent_result.stdout),
                            stderr=str(exc),
                            error_type="INVALID_PATCH",
                            exact_cost=agent_result.exact_cost,
                        )
                        completed += 1
                        continue
                    artifact_directory = self.paths.runs / run_id
                    artifact_directory.mkdir(parents=True, exist_ok=False)
                    patch_path = artifact_directory / "agent.patch"
                    patch_path.write_text(patch, encoding="utf-8", newline="\n")
                    try:
                        verification = self.verifier.verify(task, patch)
                    except RepoArenaError as exc:
                        self.database.finish_run(
                            run_id,
                            status=RunStatus.VERIFICATION_ERROR,
                            duration_seconds=time.monotonic() - started,
                            patch_size=inspection.size_bytes,
                            files_changed=len(inspection.files),
                            stdout=redact(agent_result.stdout),
                            stderr=redact(str(exc)),
                            error_type=type(exc).__name__,
                            exact_cost=agent_result.exact_cost,
                            patch_path=patch_path,
                        )
                        completed += 1
                        continue
                    self.database.add_verification(run_id, verification)
                    self.database.finish_run(
                        run_id,
                        status=verification.status,
                        duration_seconds=time.monotonic() - started,
                        patch_size=inspection.size_bytes,
                        files_changed=len(inspection.files),
                        stdout=redact(agent_result.stdout),
                        stderr=redact(agent_result.stderr),
                        error_type=None
                        if verification.status is RunStatus.PASS
                        else verification.status.value,
                        exact_cost=agent_result.exact_cost,
                        patch_path=patch_path,
                    )
                    completed += 1
        except BaseException:
            self.database.interrupt_session(session_id)
            raise
        else:
            self.database.complete_session(session_id)
        return session_id, completed


def run_benchmark_command(
    console: Console,
    context: Callable[[], tuple[RepoArenaPaths, Database]],
    *,
    agent: str | None,
    all_agents: bool,
) -> int:
    try:
        paths, database = context()
        config = load_config(paths)
        repository = GitRepository(paths.repository)
        docker = DockerRunner(config.sandbox)
        agents = select_agents(config, docker, agent=agent, all_agents=all_agents)
        verifier = Verifier(repository, paths, config, docker)
        orchestrator = BenchmarkOrchestrator(
            repository,
            paths,
            database,
            verifier,
            PatchValidator(
                max_files=config.benchmark.max_patch_files,
                max_lines=config.benchmark.max_patch_lines,
                max_bytes=config.benchmark.max_patch_bytes,
            ),
        )
        session_id, completed = orchestrator.run(
            agents, timeout_seconds=config.benchmark.timeout_seconds
        )
    except RepoArenaError as exc:
        console.print(f"[red]Benchmark failed:[/red] {exc}")
        return 1
    console.print(f"[green]Benchmark session complete:[/green] {session_id}")
    console.print(f"{completed} runs recorded. Run `repoarena report` for comparison.")
    return 0
