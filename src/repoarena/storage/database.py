from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repoarena.benchmark.models import BenchmarkTaskV1, RunStatus, VerificationResult
from repoarena.exceptions import StorageError
from repoarena.utils.redaction import redact

SCHEMA_VERSION = 2

MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS repositories (
    id TEXT PRIMARY KEY,
    root_path TEXT NOT NULL,
    remote_url TEXT NOT NULL,
    default_branch TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benchmark_tasks (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL,
    base_commit TEXT NOT NULL,
    task_json TEXT NOT NULL,
    verifier_json TEXT NOT NULL,
    quality_score INTEGER NOT NULL,
    quality_reasons_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_repository ON benchmark_tasks(repository_id, status);
CREATE TABLE IF NOT EXISTS benchmark_sessions (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    task_set_hash TEXT NOT NULL,
    agents_json TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    version TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES benchmark_sessions(id) ON DELETE CASCADE,
    task_id TEXT NOT NULL REFERENCES benchmark_tasks(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(id),
    status TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    patch_size INTEGER NOT NULL DEFAULT 0,
    files_changed INTEGER NOT NULL DEFAULT 0,
    stdout TEXT NOT NULL DEFAULT '',
    stderr TEXT NOT NULL DEFAULT '',
    error_type TEXT,
    exact_cost REAL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(session_id, task_id, agent_id)
);
CREATE INDEX IF NOT EXISTS idx_runs_session ON benchmark_runs(session_id);
CREATE TABLE IF NOT EXISTS verification_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    command_json TEXT NOT NULL,
    exit_code INTEGER,
    stdout TEXT NOT NULL,
    stderr TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    repository_commit TEXT NOT NULL
);
"""

MIGRATION_2 = """
ALTER TABLE benchmark_runs ADD COLUMN patch_path TEXT;
"""

MIGRATIONS = {1: MIGRATION_1, 2: MIGRATION_2}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self.path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"SQLite operation failed: {exc}") from exc
        finally:
            if "connection" in locals():
                connection.close()

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
                )"""
            )
            row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            current = int(row[0] or 0)
            if current > SCHEMA_VERSION:
                raise StorageError(
                    f"Database schema {current} is newer than supported schema {SCHEMA_VERSION}"
                )
            for version in range(current + 1, SCHEMA_VERSION + 1):
                migration = MIGRATIONS[version]
                applied_at = utc_now().replace("'", "''")
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + migration
                    + f"\nINSERT INTO schema_migrations(version, applied_at) VALUES ({version}, '{applied_at}');\n"
                    + "COMMIT;"
                )

    def upsert_repository(
        self, repository_id: str, root_path: Path, remote_url: str, default_branch: str | None
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO repositories(id, root_path, remote_url, default_branch, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET root_path=excluded.root_path,
                    remote_url=excluded.remote_url, default_branch=excluded.default_branch,
                    updated_at=excluded.updated_at
                """,
                (repository_id, str(root_path), remote_url, default_branch, now, now),
            )

    def upsert_task(self, task: BenchmarkTaskV1) -> None:
        now = utc_now()
        task_json = task.model_dump_json(exclude={"verification"})
        verifier_json = task.verification.model_dump_json()
        reasons = json.dumps([reason.model_dump() for reason in task.metadata.quality_reasons])
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO benchmark_tasks(
                    id, repository_id, schema_version, base_commit, task_json, verifier_json,
                    quality_score, quality_reasons_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET task_json=excluded.task_json,
                    verifier_json=excluded.verifier_json, quality_score=excluded.quality_score,
                    quality_reasons_json=excluded.quality_reasons_json, status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    task.id,
                    task.repository_id,
                    task.schema_version,
                    task.base_commit,
                    task_json,
                    verifier_json,
                    task.metadata.quality_score,
                    reasons,
                    task.status.value,
                    now,
                    now,
                ),
            )

    def list_tasks(self, repository_id: str, *, valid_only: bool = True) -> list[BenchmarkTaskV1]:
        query = "SELECT task_json, verifier_json FROM benchmark_tasks WHERE repository_id = ?"
        params: list[Any] = [repository_id]
        if valid_only:
            query += " AND status = 'VALID'"
        query += " ORDER BY quality_score DESC, id"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        tasks: list[BenchmarkTaskV1] = []
        for row in rows:
            public = json.loads(row["task_json"])
            public["verification"] = json.loads(row["verifier_json"])
            tasks.append(BenchmarkTaskV1.model_validate(public))
        return tasks

    def create_session(self, repository_id: str, task_set_hash: str, agents: Sequence[str]) -> str:
        session_id = str(uuid.uuid4())
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO benchmark_sessions
                (id, repository_id, task_set_hash, agents_json, status, started_at)
                VALUES (?, ?, ?, ?, 'RUNNING', ?)""",
                (session_id, repository_id, task_set_hash, json.dumps(list(agents)), utc_now()),
            )
        return session_id

    def complete_session(self, session_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE benchmark_sessions SET status='COMPLETE', completed_at=? WHERE id=?",
                (utc_now(), session_id),
            )

    def interrupt_session(self, session_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE benchmark_runs
                SET status='AGENT_ERROR', error_type='INTERRUPTED',
                    stderr='Benchmark controller stopped before this run completed.',
                    completed_at=?
                WHERE session_id=? AND status='RUNNING'""",
                (utc_now(), session_id),
            )
            connection.execute(
                """UPDATE benchmark_sessions
                SET status='INTERRUPTED', completed_at=? WHERE id=?""",
                (utc_now(), session_id),
            )

    def recover_interrupted_sessions(self, repository_id: str) -> int:
        """Close stale RUNNING rows left by an interrupted controller process."""
        with self.connect() as connection:
            sessions = connection.execute(
                "SELECT id FROM benchmark_sessions WHERE repository_id=? AND status='RUNNING'",
                (repository_id,),
            ).fetchall()
            if not sessions:
                return 0
            session_ids = [str(row["id"]) for row in sessions]
            now = utc_now()
            connection.executemany(
                """UPDATE benchmark_runs
                SET status='AGENT_ERROR', error_type='INTERRUPTED',
                    stderr='Benchmark controller was interrupted before this run completed.',
                    completed_at=?
                WHERE status='RUNNING' AND session_id=?""",
                [(now, session_id) for session_id in session_ids],
            )
            connection.executemany(
                """UPDATE benchmark_sessions
                SET status='INTERRUPTED', completed_at=?
                WHERE id=?""",
                [(now, session_id) for session_id in session_ids],
            )
            return len(session_ids)

    def upsert_agent(self, name: str, version: str | None, model: str | None) -> str:
        agent_id = name
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO agents(id, name, version, model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET version=excluded.version,
                    model=excluded.model, updated_at=excluded.updated_at
                """,
                (agent_id, name, version, model, now, now),
            )
        return agent_id

    def create_run(self, session_id: str, task_id: str, agent_id: str) -> str:
        run_id = str(uuid.uuid4())
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO benchmark_runs
                (id, session_id, task_id, agent_id, status, duration_seconds, started_at)
                VALUES (?, ?, ?, ?, 'RUNNING', 0, ?)""",
                (run_id, session_id, task_id, agent_id, utc_now()),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        duration_seconds: float,
        patch_size: int,
        files_changed: int,
        stdout: str,
        stderr: str,
        error_type: str | None,
        exact_cost: float | None,
        patch_path: Path | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE benchmark_runs SET status=?, duration_seconds=?, patch_size=?,
                    files_changed=?, stdout=?, stderr=?, error_type=?, exact_cost=?,
                    patch_path=?, completed_at=?
                WHERE id=?
                """,
                (
                    status.value,
                    duration_seconds,
                    patch_size,
                    files_changed,
                    stdout,
                    stderr,
                    error_type,
                    exact_cost,
                    str(patch_path) if patch_path else None,
                    utc_now(),
                    run_id,
                ),
            )

    def add_verification(self, run_id: str, result: VerificationResult) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO verification_results
                (id, run_id, status, command_json, exit_code, stdout, stderr,
                 duration_seconds, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    run_id,
                    result.status.value,
                    json.dumps(result.command),
                    result.exit_code,
                    redact(result.stdout),
                    redact(result.stderr),
                    result.duration_seconds,
                    utc_now(),
                ),
            )

    def report_rows(self, repository_id: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT r.id, r.status, r.duration_seconds, r.patch_size, r.files_changed,
                       r.error_type, r.exact_cost, r.patch_path, r.stdout AS run_stdout,
                       r.stderr AS run_stderr, r.completed_at, a.name AS agent,
                       a.version, a.model, t.id AS task_id, t.quality_score,
                       v.status AS verification_status, v.stdout AS test_stdout,
                       v.stderr AS test_stderr
                FROM benchmark_runs r
                JOIN benchmark_sessions s ON s.id = r.session_id
                JOIN benchmark_tasks t ON t.id = r.task_id
                JOIN agents a ON a.id = r.agent_id
                LEFT JOIN verification_results v ON v.run_id = r.id
                WHERE s.repository_id = ? AND s.status = 'COMPLETE' AND r.status != 'RUNNING'
                  AND s.task_set_hash = (
                    SELECT task_set_hash FROM benchmark_sessions
                    WHERE repository_id = ? AND status = 'COMPLETE'
                    ORDER BY completed_at DESC LIMIT 1
                  )
                ORDER BY r.completed_at, a.name, t.id
                """,
                (repository_id, repository_id),
            ).fetchall()

    def add_report(self, repository_id: str, path: Path, repository_commit: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO reports(id, repository_id, path, generated_at, repository_commit) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), repository_id, str(path), utc_now(), repository_commit),
            )
