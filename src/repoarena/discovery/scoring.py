from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from repoarena.benchmark.models import QualityReason

_DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt", ".adoc"}
_DEPENDENCY_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "requirements.txt",
    "go.sum",
    "cargo.lock",
}
_GENERATED_PARTS = {"dist", "build", "vendor", "generated", "node_modules", "coverage"}
_SOURCE_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".scala",
    ".vue",
    ".svelte",
}


def is_test_path(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    return (
        any(
            part in {"test", "tests", "spec", "specs", "__tests__"}
            for part in PurePosixPath(lowered).parts
        )
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or name.endswith("_test.go")
    )


def is_source_path(path: str) -> bool:
    return PurePosixPath(path.lower()).suffix in _SOURCE_SUFFIXES and not is_test_path(path)


def languages_for(paths: tuple[str, ...]) -> list[str]:
    mapping = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".kt": "Kotlin",
        ".c": "C",
        ".cc": "C++",
        ".cpp": "C++",
        ".cs": "C#",
        ".rb": "Ruby",
    }
    return sorted(
        {
            mapping[suffix]
            for path in paths
            if (suffix := PurePosixPath(path).suffix.lower()) in mapping
        }
    )


@dataclass(frozen=True, slots=True)
class CandidateFacts:
    linked_issue: bool
    clear_description: bool
    merged: bool
    ci_success: bool
    files: tuple[str, ...]
    lines_changed: int
    whitespace_only: bool
    reproducible_environment: bool

    @property
    def test_paths(self) -> tuple[str, ...]:
        return tuple(path for path in self.files if is_test_path(path))

    @property
    def source_paths(self) -> tuple[str, ...]:
        return tuple(path for path in self.files if is_source_path(path))


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: int
    reasons: tuple[QualityReason, ...]
    rejection: str | None


def score_candidate(
    facts: CandidateFacts,
    *,
    threshold: int,
    max_files: int = 50,
    max_lines: int = 2_000,
) -> ScoreResult:
    if not facts.files:
        return ScoreResult(0, (), "merge-only change")
    if facts.whitespace_only:
        return ScoreResult(0, (), "formatting-only change")
    if not facts.clear_description:
        return ScoreResult(0, (), "unclear task description")
    if all(PurePosixPath(path).suffix.lower() in _DOC_SUFFIXES for path in facts.files):
        return ScoreResult(0, (), "documentation-only change")
    if all(PurePosixPath(path).name.lower() in _DEPENDENCY_FILES for path in facts.files):
        return ScoreResult(0, (), "dependency-only change")
    if all(set(PurePosixPath(path.lower()).parts) & _GENERATED_PARTS for path in facts.files):
        return ScoreResult(0, (), "generated-code-only change")
    if not facts.test_paths:
        return ScoreResult(0, (), "no executable test change")
    if not facts.source_paths:
        return ScoreResult(0, (), "no source code change")
    if len(facts.files) > max_files or facts.lines_changed > max_lines:
        return ScoreResult(0, (), "oversized change")
    if not facts.reproducible_environment:
        return ScoreResult(0, (), "unsupported verification environment")

    signals = (
        (facts.linked_issue, "linked_issue", 20, "A linked issue supplies the task intent."),
        (bool(facts.test_paths), "tests_changed", 25, "Tests were added or modified."),
        (bool(facts.source_paths), "source_changed", 15, "Production source code changed."),
        (facts.clear_description, "clear_description", 10, "The task description is actionable."),
        (facts.merged, "merged", 10, "The pull request was merged."),
        (facts.ci_success, "ci_success", 10, "GitHub reports successful CI evidence."),
        (
            len(facts.files) <= max_files and facts.lines_changed <= max_lines,
            "reasonable_size",
            5,
            "Patch size is bounded.",
        ),
        (
            facts.reproducible_environment,
            "reproducible",
            5,
            "A supported verifier profile was detected.",
        ),
    )
    reasons = tuple(
        QualityReason(signal=name, points=points, detail=detail)
        for enabled, name, points, detail in signals
        if enabled
    )
    score = sum(reason.points for reason in reasons)
    rejection = None if score >= threshold else f"quality score {score} below threshold {threshold}"
    return ScoreResult(score, reasons, rejection)
