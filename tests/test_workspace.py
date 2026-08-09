from __future__ import annotations

from pathlib import Path

import pytest

from repoarena.benchmark.workspace import PatchValidator, WorkspaceFactory, audit_history
from repoarena.exceptions import RepositoryError
from repoarena.utils.process import run_process


def test_solver_contains_one_synthetic_commit_and_no_future_objects(
    synthetic_repository: object,
) -> None:
    fixture = synthetic_repository
    factory = WorkspaceFactory(fixture.git)

    with factory.materialize(fixture.base, solver=True) as workspace:
        audit = audit_history(workspace)
        gold_lookup = run_process(
            ["git", "cat-file", "-e", f"{fixture.gold}^{{commit}}"],
            cwd=workspace,
            check=False,
        )
        assert len(audit["log"].strip().splitlines()) == 1
        assert "benchmark" in audit["branches"]
        assert audit["tags"] == ""
        assert audit["reflog"] == ""
        assert audit["fsck"] == ""
        assert audit["remotes"] == ""
        assert gold_lookup.returncode != 0
        assert not (workspace / ".repoarena").exists()


def test_workspace_is_destroyed_after_context(synthetic_repository: object) -> None:
    fixture = synthetic_repository
    with WorkspaceFactory(fixture.git).materialize(fixture.base, solver=True) as workspace:
        captured = Path(workspace)
        assert captured.exists()
    assert not captured.exists()


def test_patch_validator_rejects_traversal_and_hidden_test_changes() -> None:
    validator = PatchValidator(max_files=10, max_lines=100)
    with pytest.raises(RepositoryError, match="Unsafe patch path"):
        validator.inspect("diff --git a/../../secret b/../../secret\n")
    with pytest.raises(RepositoryError, match="protected verifier paths"):
        validator.inspect(
            "diff --git a/tests/hidden.py b/tests/hidden.py\n--- a/tests/hidden.py\n"
            "+++ b/tests/hidden.py\n@@ -1 +1 @@\n-a\n+b\n",
            protected_paths=("tests/hidden.py",),
        )

    with pytest.raises(RepositoryError, match="protected verifier paths"):
        validator.inspect(
            "diff --git a/tests/hidden.py b/tests/renamed.py\n"
            "similarity index 100%\nrename from tests/hidden.py\nrename to tests/renamed.py\n",
            protected_paths=("tests/hidden.py",),
        )
    with pytest.raises(RepositoryError, match="Symlink and submodule"):
        validator.inspect(
            "diff --git a/vendor/tool b/vendor/tool\nnew file mode 160000\n"
            "index 0000000..1234567\n",
        )
