from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from rich.console import Console

from repoarena.benchmark.models import (
    BenchmarkTaskV1,
    TaskMetadata,
    TaskStatus,
    VerifierSpecV1,
)
from repoarena.config import RepoArenaConfig, RepoArenaPaths, load_config
from repoarena.discovery.github import GitHubMetadataSource, MetadataSource
from repoarena.discovery.models import DiscoveryStats, PullRequestMetadata
from repoarena.discovery.scoring import CandidateFacts, languages_for, score_candidate
from repoarena.exceptions import RepoArenaError
from repoarena.git import GitRepository
from repoarena.storage import Database
from repoarena.verification.profiles import detect_profile

_SHA = re.compile(r"\b[0-9a-fA-F]{40}\b")
_GITHUB_URL = re.compile(r"https?://github\.com/\S+", re.IGNORECASE)
_REFERENCE = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+")
_NUMBER_REFERENCE = re.compile(r"(?<![\w])#\d+\b")


class DiscoveryService:
    def __init__(
        self,
        repository: GitRepository,
        paths: RepoArenaPaths,
        config: RepoArenaConfig,
        database: Database,
        metadata_source: MetadataSource,
        baseline_validator: Callable[[BenchmarkTaskV1], tuple[bool, str]],
    ) -> None:
        self.repository = repository
        self.paths = paths
        self.config = config
        self.database = database
        self.metadata_source = metadata_source
        self.baseline_validator = baseline_validator

    def discover(self, *, limit: int | None = None) -> DiscoveryStats:
        pulls = self.metadata_source.merged_pull_requests(limit=limit)
        stats = DiscoveryStats(merged_prs=len(pulls))
        stats.linked_issues = sum(pull.issue is not None for pull in pulls)
        commits = [pull.merge_commit for pull in pulls]
        source = (
            self.repository.source_with_commits(
                commits, self.paths.cache, require_first_parents=True
            )
            if commits
            else self.repository
        )
        for pull in pulls:
            try:
                task, rejection = self._candidate(source, pull)
            except RepoArenaError as exc:
                stats.reject(type(exc).__name__)
                continue
            if rejection:
                stats.reject(rejection)
                continue
            if task is None:
                stats.reject("candidate construction failed")
                continue
            stats.potential_candidates += 1
            valid, detail = self.baseline_validator(task)
            if not valid:
                stats.reject(f"baseline: {detail}")
                continue
            task.status = TaskStatus.VALID
            self.database.upsert_task(task)
            stats.valid_tasks += 1
        return stats

    def _candidate(
        self, repository: GitRepository, pull: PullRequestMetadata
    ) -> tuple[BenchmarkTaskV1 | None, str | None]:
        base = repository.first_parent(pull.merge_commit)
        diff = repository.diff_stats(base, pull.merge_commit)
        description = _description(pull, diff.files)
        profile = detect_profile(
            repository,
            base,
            tuple(path for path in diff.files if _is_test(path)),
            self.config.verification,
        )
        facts = CandidateFacts(
            linked_issue=pull.issue is not None,
            clear_description=len(description) >= 80,
            merged=True,
            ci_success=pull.ci_success,
            files=diff.files,
            lines_changed=diff.lines_changed,
            whitespace_only=repository.is_whitespace_only(base, pull.merge_commit),
            reproducible_environment=profile is not None,
        )
        score = score_candidate(
            facts,
            threshold=self.config.benchmark.quality_threshold,
            max_files=self.config.benchmark.max_patch_files,
            max_lines=self.config.benchmark.max_patch_lines,
        )
        if score.rejection or profile is None:
            return None, score.rejection or "unsupported verification environment"
        test_paths = facts.test_paths
        hidden_patch = repository.diff_patch(base, pull.merge_commit, include_paths=test_paths)
        gold_source_patch = repository.diff_patch(base, pull.merge_commit, exclude_paths=test_paths)
        if not hidden_patch.strip() or not gold_source_patch.strip():
            return None, "task does not separate into hidden tests and source changes"
        task_id = hashlib.sha256(
            f"1\0{self.repository.repository_id}\0{pull.number}\0{base}\0{pull.merge_commit}".encode()
        ).hexdigest()[:24]
        task = BenchmarkTaskV1(
            id=task_id,
            repository_id=self.repository.repository_id,
            repository=self.repository.remote_url,
            base_commit=base,
            gold_commit=pull.merge_commit,
            task_description=description,
            issue_reference=pull.issue.url if pull.issue else None,
            pull_request_number=pull.number,
            verification=VerifierSpecV1(
                image=profile.image,
                setup_commands=list(profile.setup_commands),
                test_command=profile.test_command,
                hidden_test_patch=hidden_patch,
                gold_source_patch=gold_source_patch,
                protected_paths=list(test_paths),
                repetitions=self.config.benchmark.baseline_repetitions,
            ),
            metadata=TaskMetadata(
                languages=languages_for(diff.files),
                quality_score=score.score,
                quality_reasons=list(score.reasons),
                files_changed_count=len(diff.files),
                lines_changed=diff.lines_changed,
            ),
        )
        return task, None


def _is_test(path: str) -> bool:
    from repoarena.discovery.scoring import is_test_path

    return is_test_path(path)


def _description(pull: PullRequestMetadata, forbidden_paths: tuple[str, ...]) -> str:
    title = pull.issue.title if pull.issue else pull.title
    body = pull.issue.body if pull.issue else pull.body
    text = f"{title.strip()}\n\n{body.strip()}".strip()
    text = _GITHUB_URL.sub("[reference removed]", text)
    text = _SHA.sub("[commit removed]", text)
    text = _REFERENCE.sub("", text)
    text = _NUMBER_REFERENCE.sub("[reference removed]", text)
    for path in sorted(forbidden_paths, key=len, reverse=True):
        text = re.sub(re.escape(path), "[path removed]", text, flags=re.IGNORECASE)
    return text[:20_000].strip()


def run_discovery_command(
    console: Console,
    context: Callable[[], tuple[RepoArenaPaths, Database]],
    *,
    limit: int | None,
) -> int:
    try:
        paths, database = context()
        config = load_config(paths)
        repository = GitRepository(paths.repository)
        database.upsert_repository(
            repository.repository_id,
            paths.repository,
            repository.remote_url,
            repository.default_branch,
        )
        from repoarena.verification.verifier import Verifier

        verifier = Verifier(repository, paths, config)
        service = DiscoveryService(
            repository,
            paths,
            config,
            database,
            GitHubMetadataSource(repository.remote_url, config.github),
            verifier.validate_baseline,
        )
        stats = service.discover(limit=limit)
    except RepoArenaError as exc:
        console.print(f"[red]Discovery failed:[/red] {exc}")
        return 1
    console.print("[bold]Repository analyzed.[/bold]")
    console.print(f"{stats.merged_prs} merged PRs found")
    console.print(f"{stats.linked_issues} linked issues found")
    console.print(f"{stats.potential_candidates} potential benchmark candidates")
    console.print(f"[green]{stats.valid_tasks} high-quality benchmark tasks generated[/green]")
    if stats.rejected:
        console.print("\nRejected candidates:")
        for reason, count in sorted(stats.rejected.items()):
            console.print(f"  {count:>3}  {reason}")
    return 0
