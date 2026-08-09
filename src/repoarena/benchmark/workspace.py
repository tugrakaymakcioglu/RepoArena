from __future__ import annotations

import io
import os
import re
import shutil
import stat
import tarfile
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repoarena.exceptions import RepositoryError
from repoarena.git import GitRepository
from repoarena.utils.process import run_process

_DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class PatchInspection:
    files: tuple[str, ...]
    lines_changed: int
    size_bytes: int


class PatchValidator:
    def __init__(self, *, max_files: int, max_lines: int, max_bytes: int = 5_000_000) -> None:
        self.max_files = max_files
        self.max_lines = max_lines
        self.max_bytes = max_bytes

    def inspect(self, patch: str, *, protected_paths: tuple[str, ...] = ()) -> PatchInspection:
        if "\x00" in patch:
            raise RepositoryError("Patch contains a NUL byte")
        if "GIT binary patch" in patch or "Binary files " in patch:
            raise RepositoryError("Binary patches are not supported in V1")
        if re.search(r"^(?:new file mode|old mode|new mode) 1[26]0000$", patch, re.MULTILINE):
            raise RepositoryError("Symlink and submodule patches are not supported")
        size_bytes = len(patch.encode("utf-8"))
        if size_bytes > self.max_bytes:
            raise RepositoryError(f"Patch is {size_bytes} bytes; limit is {self.max_bytes}")
        files: list[str] = []
        for before, after in _DIFF_HEADER.findall(patch):
            for path in (before, after):
                self._validate_path(path)
                files.append(path)
        unique_files = tuple(dict.fromkeys(files))
        if patch.strip() and not unique_files:
            raise RepositoryError("Patch is not a recognized Git diff")
        if len(unique_files) > self.max_files:
            raise RepositoryError(
                f"Patch changes {len(unique_files)} files; limit is {self.max_files}"
            )
        protected = {PurePosixPath(path).as_posix().casefold() for path in protected_paths}
        overlap = protected.intersection(path.casefold() for path in unique_files)
        if overlap:
            raise RepositoryError(
                f"Patch changes protected verifier paths: {', '.join(sorted(overlap))}"
            )
        changed = sum(
            1
            for line in patch.splitlines()
            if (line.startswith("+") and not line.startswith("+++"))
            or (line.startswith("-") and not line.startswith("---"))
        )
        if changed > self.max_lines:
            raise RepositoryError(f"Patch changes {changed} lines; limit is {self.max_lines}")
        return PatchInspection(unique_files, changed, size_bytes)

    @staticmethod
    def _validate_path(value: str) -> None:
        if "\\" in value or value.startswith("/"):
            raise RepositoryError(f"Unsafe patch path: {value}")
        path = PurePosixPath(value)
        if not value or ".." in path.parts or path.parts[0] in {".git", ".repoarena"}:
            raise RepositoryError(f"Unsafe patch path: {value}")


class WorkspaceFactory:
    def __init__(self, repository: GitRepository) -> None:
        self.repository = repository

    @contextmanager
    def materialize(self, commit: str, *, solver: bool) -> Iterator[Path]:
        submodules = self.repository.submodule_paths(commit)
        if submodules:
            raise RepositoryError(
                "Historical snapshots with submodules are unsupported: " + ", ".join(submodules[:5])
            )
        temporary = Path(
            tempfile.mkdtemp(prefix="repoarena-solver-" if solver else "repoarena-verifier-")
        )
        try:
            self._extract(self.repository.archive(commit), temporary)
            if solver:
                state = temporary / ".repoarena"
                if state.exists():
                    shutil.rmtree(state)
            run_process(["git", "init", "-b", "benchmark"], cwd=temporary)
            run_process(["git", "config", "user.name", "RepoArena"], cwd=temporary)
            run_process(["git", "config", "user.email", "benchmark@localhost"], cwd=temporary)
            run_process(["git", "config", "core.logAllRefUpdates", "false"], cwd=temporary)
            run_process(["git", "add", "-A"], cwd=temporary)
            run_process(
                ["git", "commit", "--allow-empty", "-m", "Historical benchmark base"],
                cwd=temporary,
                env={
                    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
                    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
                },
            )
            logs = temporary / ".git" / "logs"
            if logs.exists():
                shutil.rmtree(logs)
            yield temporary
        finally:
            _remove_tree(temporary)

    @staticmethod
    def _extract(archive: bytes, destination: Path) -> None:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            for member in tar.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts:
                    raise RepositoryError(f"Unsafe archive member: {member.name}")
                if member.issym() or member.islnk():
                    target = PurePosixPath(member.linkname)
                    if target.is_absolute() or ".." in target.parts:
                        raise RepositoryError(f"Unsafe archive link: {member.name}")
            tar.extractall(destination, filter="data")


def capture_patch(workspace: Path) -> str:
    status = run_process(["git", "status", "--porcelain", "-z"], cwd=workspace).stdout
    if not status:
        return ""
    run_process(["git", "add", "--intent-to-add", "--all"], cwd=workspace)
    return run_process(
        ["git", "diff", "--binary", "--full-index", "--no-ext-diff", "HEAD", "--"],
        cwd=workspace,
    ).stdout


def audit_history(workspace: Path) -> dict[str, str]:
    commands = {
        "log": ["git", "log", "--oneline", "--all"],
        "branches": ["git", "branch", "-a"],
        "tags": ["git", "tag"],
        "reflog": ["git", "reflog", "show", "--all"],
        "fsck": ["git", "fsck", "--no-reflogs", "--unreachable"],
        "remotes": ["git", "remote", "-v"],
    }
    return {
        name: run_process(argv, cwd=workspace, check=False).stdout
        for name, argv in commands.items()
    }


def _remove_tree(path: Path) -> None:
    def make_writable(function: Callable[[str], object], value: str, exc_info: object) -> None:
        del exc_info
        os.chmod(value, stat.S_IWRITE)
        function(value)

    if path.exists():
        shutil.rmtree(path, onexc=make_writable)
