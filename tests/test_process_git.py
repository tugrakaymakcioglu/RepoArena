from __future__ import annotations

import sys
from pathlib import Path

import pytest

from repoarena.exceptions import RepositoryError
from repoarena.git import GitRepository
from repoarena.utils.process import ProcessFailure, run_process


def test_malformed_repository_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RepositoryError, match="Not a valid Git repository"):
        GitRepository(tmp_path)


def test_subprocess_failure_preserves_diagnostics() -> None:
    with pytest.raises(ProcessFailure, match="intentional failure") as captured:
        run_process(
            [
                sys.executable,
                "-c",
                "import sys; print('intentional failure', file=sys.stderr); sys.exit(7)",
            ]
        )

    assert captured.value.result.returncode == 7
    assert captured.value.result.argv[0] == sys.executable


def test_shallow_history_uses_private_mirror(synthetic_repository: object, tmp_path: Path) -> None:
    fixture = synthetic_repository
    remote = tmp_path / "remote.git"
    shallow = tmp_path / "shallow"
    run_process(["git", "clone", "--bare", str(fixture.path), str(remote)])
    run_process(["git", "clone", "--depth", "1", remote.as_uri(), str(shallow)])
    repository = GitRepository(shallow)

    assert repository.has_commit(fixture.gold)
    assert not repository.has_first_parent(fixture.gold)
    source = repository.source_with_commits(
        [fixture.gold], tmp_path / "cache", require_first_parents=True
    )

    assert source.has_commit(fixture.base)
    assert source.first_parent(fixture.gold) == fixture.base
