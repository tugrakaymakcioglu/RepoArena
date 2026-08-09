from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w
from pydantic import ValidationError

from repoarena.config.models import RepoArenaConfig
from repoarena.exceptions import ConfigurationError
from repoarena.utils.process import run_process

MANAGED_IGNORE_HEADER = "# RepoArena local state (managed by repoarena init)"
MANAGED_IGNORE_LINES = (
    ".repoarena/repoarena.db",
    ".repoarena/repoarena.db-*",
    ".repoarena/cache/",
    ".repoarena/tasks/",
    ".repoarena/runs/",
    ".repoarena/reports/",
)


@dataclass(frozen=True, slots=True)
class RepoArenaPaths:
    repository: Path
    state: Path
    config: Path
    database: Path
    tasks: Path
    runs: Path
    reports: Path
    cache: Path

    @classmethod
    def for_repository(cls, repository: Path) -> RepoArenaPaths:
        state = repository / ".repoarena"
        return cls(
            repository=repository,
            state=state,
            config=state / "config.toml",
            database=state / "repoarena.db",
            tasks=state / "tasks",
            runs=state / "runs",
            reports=state / "reports",
            cache=state / "cache",
        )


def find_repository(start: Path) -> Path:
    result = run_process(["git", "rev-parse", "--show-toplevel"], cwd=start, check=False)
    if result.returncode != 0:
        raise ConfigurationError(f"Not a Git repository: {start.resolve()}")
    return Path(result.stdout.strip()).resolve()


def initialize(start: Path) -> tuple[RepoArenaPaths, bool]:
    repository = find_repository(start)
    paths = RepoArenaPaths.for_repository(repository)
    paths.state.mkdir(exist_ok=True)
    for directory in (paths.tasks, paths.runs, paths.reports, paths.cache):
        directory.mkdir(exist_ok=True)

    created = not paths.config.exists()
    if created:
        serialized = tomli_w.dumps(RepoArenaConfig().model_dump(mode="json", exclude_none=True))
        paths.config.write_text(serialized, encoding="utf-8", newline="\n")
    else:
        load_config(paths)
    _update_gitignore(repository / ".gitignore")
    return paths, created


def load_config(paths: RepoArenaPaths) -> RepoArenaConfig:
    if not paths.config.is_file():
        raise ConfigurationError("RepoArena is not initialized. Run `repoarena init` first.")
    try:
        raw = tomllib.loads(paths.config.read_text(encoding="utf-8"))
        return RepoArenaConfig.model_validate(raw)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ConfigurationError(f"Invalid configuration at {paths.config}: {exc}") from exc


def _update_gitignore(path: Path) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [line for line in MANAGED_IGNORE_LINES if line not in existing.splitlines()]
    if not missing:
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    block = "\n".join((MANAGED_IGNORE_HEADER, *missing)) + "\n"
    path.write_text(existing + prefix + block, encoding="utf-8", newline="\n")
