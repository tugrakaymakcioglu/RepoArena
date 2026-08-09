from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from repoarena.exceptions import RepositoryError
from repoarena.utils.process import ProcessFailure, ProcessResult, run_process, run_process_bytes


@dataclass(frozen=True, slots=True)
class DiffStats:
    files: tuple[str, ...]
    additions: int
    deletions: int

    @property
    def lines_changed(self) -> int:
        return self.additions + self.deletions


class GitRepository:
    """Read-only access to a Git object database."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        result = self.git("rev-parse", "--git-dir", check=False)
        if result.returncode != 0:
            raise RepositoryError(f"Not a valid Git repository: {self.path}")

    def git(self, *args: str, check: bool = True) -> ProcessResult:
        return run_process(["git", *args], cwd=self.path, check=check)

    @property
    def remote_url(self) -> str:
        result = self.git("remote", "get-url", "origin", check=False)
        if result.returncode != 0 or not result.stdout.strip():
            raise RepositoryError("Git remote 'origin' is required for GitHub discovery")
        return result.stdout.strip()

    @property
    def repository_id(self) -> str:
        identity = normalize_remote(self.remote_url)
        return hashlib.sha256(identity.encode()).hexdigest()[:24]

    @property
    def default_branch(self) -> str | None:
        symbolic = self.git("symbolic-ref", "refs/remotes/origin/HEAD", check=False)
        if symbolic.returncode == 0:
            return symbolic.stdout.strip().rsplit("/", 1)[-1]
        branch = self.git("branch", "--show-current", check=False)
        return branch.stdout.strip() or None

    @property
    def head_commit(self) -> str:
        result = self.git("rev-parse", "HEAD", check=False)
        return result.stdout.strip() if result.returncode == 0 else "unborn"

    def has_commit(self, commit: str) -> bool:
        return self.git("cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode == 0

    def has_first_parent(self, commit: str) -> bool:
        return self.git("cat-file", "-e", f"{commit}^1^{{commit}}", check=False).returncode == 0

    def first_parent(self, commit: str) -> str:
        result = self.git("rev-parse", f"{commit}^1", check=False)
        if result.returncode != 0:
            raise RepositoryError(f"Merged commit has no historical first parent: {commit}")
        return result.stdout.strip()

    def diff_stats(self, base: str, gold: str) -> DiffStats:
        names = self.git("diff", "--name-only", "-z", base, gold).stdout.split("\x00")
        files = tuple(name for name in names if name)
        additions = 0
        deletions = 0
        for line in self.git("diff", "--numstat", base, gold).stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) < 3:
                continue
            if parts[0].isdigit():
                additions += int(parts[0])
            if parts[1].isdigit():
                deletions += int(parts[1])
        return DiffStats(files, additions, deletions)

    def diff_patch(
        self,
        base: str,
        gold: str,
        *,
        include_paths: tuple[str, ...] = (),
        exclude_paths: tuple[str, ...] = (),
    ) -> str:
        args = ["diff", "--binary", "--full-index", "--no-ext-diff", base, gold]
        if include_paths or exclude_paths:
            args.append("--")
            args.extend(include_paths)
            args.extend(f":(exclude){path}" for path in exclude_paths)
        return self.git(*args).stdout

    def file_exists(self, commit: str, path: str) -> bool:
        return self.git("cat-file", "-e", f"{commit}:{path}", check=False).returncode == 0

    def read_file(self, commit: str, path: str) -> str:
        result = self.git("show", f"{commit}:{path}", check=False)
        if result.returncode != 0:
            raise RepositoryError(f"Cannot read {path} at {commit}")
        return result.stdout

    def is_whitespace_only(self, base: str, gold: str) -> bool:
        regular = self.git("diff", "--quiet", base, gold, check=False).returncode
        ignored = self.git("diff", "--quiet", "-w", base, gold, check=False).returncode
        return regular != 0 and ignored == 0

    def archive(self, commit: str) -> bytes:
        try:
            return run_process_bytes(["git", "archive", "--format=tar", commit], cwd=self.path)
        except ProcessFailure as exc:
            raise RepositoryError(f"Cannot materialize historical commit {commit}: {exc}") from exc

    def submodule_paths(self, commit: str) -> tuple[str, ...]:
        result = self.git("ls-tree", "-r", commit)
        paths: list[str] = []
        for line in result.stdout.splitlines():
            metadata, separator, path = line.partition("\t")
            if separator and metadata.startswith("160000 "):
                paths.append(path)
        return tuple(paths)

    def source_with_commits(
        self,
        commits: list[str],
        cache_directory: Path,
        *,
        require_first_parents: bool = False,
    ) -> GitRepository:
        def complete(repository: GitRepository, commit: str) -> bool:
            return repository.has_commit(commit) and (
                not require_first_parents or repository.has_first_parent(commit)
            )

        if all(complete(self, commit) for commit in commits):
            return self
        mirror = cache_directory / "repository.git"
        cache_directory.mkdir(parents=True, exist_ok=True)
        if mirror.exists():
            run_process(["git", "remote", "update", "--prune"], cwd=mirror)
        else:
            run_process(["git", "clone", "--mirror", self.remote_url, str(mirror)])
        source = GitRepository(mirror)
        missing = [commit for commit in commits if not complete(source, commit)]
        if missing:
            raise RepositoryError(f"Historical commits are unavailable: {', '.join(missing)}")
        return source


def normalize_remote(remote: str) -> str:
    value = remote.strip().replace("\\", "/")
    match = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", value, re.IGNORECASE)
    if match:
        return f"github.com/{match.group(1).lower()}/{match.group(2).lower()}"
    return value.removesuffix(".git").lower()


def github_slug(remote: str) -> tuple[str, str]:
    normalized = normalize_remote(remote)
    match = re.fullmatch(r"github\.com/([^/]+)/([^/]+)", normalized)
    if not match:
        raise RepositoryError("V1 discovery currently requires a github.com origin remote")
    return match.group(1), match.group(2)
