from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from repoarena.git import GitRepository


def git(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout.strip()


@dataclass(frozen=True, slots=True)
class SyntheticRepository:
    path: Path
    git: GitRepository
    base: str
    gold: str


@pytest.fixture()
def synthetic_repository(tmp_path: Path) -> SyntheticRepository:
    repository = tmp_path / "fixture-repository"
    repository.mkdir()
    git(repository, "init", "-b", "main")
    git(repository, "config", "user.name", "Fixture Author")
    git(repository, "config", "user.email", "fixture@example.test")
    git(repository, "remote", "add", "origin", "https://github.com/example/fixture.git")
    (repository / "pyproject.toml").write_text(
        "[build-system]\nrequires = ['hatchling']\nbuild-backend = 'hatchling.build'\n"
        "[project]\nname = 'fixture-project'\nversion = '0.0.1'\n",
        encoding="utf-8",
    )
    (repository / "calculator.py").write_text(
        "def add(left: int, right: int) -> int:\n    return left - right\n",
        encoding="utf-8",
    )
    git(repository, "add", ".")
    git(repository, "commit", "-m", "Create calculator with historical bug")
    base = git(repository, "rev-parse", "HEAD")

    (repository / "calculator.py").write_text(
        "def add(left: int, right: int) -> int:\n    return left + right\n",
        encoding="utf-8",
    )
    tests = repository / "tests"
    tests.mkdir()
    (tests / "test_calculator.py").write_text(
        "from calculator import add\n\n\ndef test_adds_positive_numbers() -> None:\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    git(repository, "add", ".")
    git(repository, "commit", "-m", "Fix addition and add regression test")
    gold = git(repository, "rev-parse", "HEAD")
    return SyntheticRepository(repository, GitRepository(repository), base, gold)
