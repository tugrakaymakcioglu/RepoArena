from __future__ import annotations

import sqlite3

from repoarena.report.generator import render_html, summarize


def row_factory(values: list[tuple[object, ...]]) -> list[sqlite3.Row]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE result(agent TEXT, task_id TEXT, status TEXT, duration_seconds REAL, "
            "quality_score INTEGER, error_type TEXT)"
        )
        connection.executemany("INSERT INTO result VALUES (?, ?, ?, ?, ?, ?)", values)
        return connection.execute("SELECT * FROM result").fetchall()
    finally:
        connection.close()


def test_report_recommends_only_on_identical_task_sets_and_escapes_html() -> None:
    rows = row_factory(
        [
            ("codex<script>", "one", "PASS", 1.0, 90, None),
            ("codex<script>", "two", "PASS", 3.0, 80, None),
            ("claude", "one", "FAIL", 2.0, 90, "<img src=x>"),
            ("claude", "two", "PASS", 4.0, 80, None),
        ]
    )
    summaries, recommendation = summarize(rows)
    page = render_html(rows, summaries, recommendation, "abc123")

    assert recommendation == "codex<script>"
    assert "codex&lt;script&gt;" in page
    assert "codex<script>" not in page
    assert "&lt;img src=x&gt;" in page
    assert "Cost" in page


def test_report_with_different_task_sets_has_no_recommendation() -> None:
    rows = row_factory(
        [("codex", "one", "PASS", 1.0, 90, None), ("claude", "two", "PASS", 1.0, 90, None)]
    )

    _, recommendation = summarize(rows)

    assert recommendation is None
