from __future__ import annotations

from dataclasses import replace

import pytest

from repoarena.discovery.scoring import CandidateFacts, score_candidate


def complete_facts() -> CandidateFacts:
    return CandidateFacts(
        linked_issue=True,
        clear_description=True,
        merged=True,
        ci_success=True,
        files=("calculator.py", "tests/test_calculator.py"),
        lines_changed=12,
        whitespace_only=False,
        reproducible_environment=True,
    )


def test_complete_candidate_scores_one_hundred() -> None:
    result = score_candidate(complete_facts(), threshold=70)

    assert result.score == 100
    assert result.rejection is None
    assert {reason.signal for reason in result.reasons} == {
        "linked_issue",
        "tests_changed",
        "source_changed",
        "clear_description",
        "merged",
        "ci_success",
        "reasonable_size",
        "reproducible",
    }


def test_candidate_without_tests_is_rejected() -> None:
    facts = complete_facts()
    result = score_candidate(
        CandidateFacts(
            linked_issue=facts.linked_issue,
            clear_description=facts.clear_description,
            merged=facts.merged,
            ci_success=facts.ci_success,
            files=("calculator.py",),
            lines_changed=facts.lines_changed,
            whitespace_only=facts.whitespace_only,
            reproducible_environment=facts.reproducible_environment,
        ),
        threshold=70,
    )

    assert result.rejection == "no executable test change"


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (replace(complete_facts(), files=("README.md",)), "documentation-only change"),
        (replace(complete_facts(), files=("uv.lock",)), "dependency-only change"),
        (
            replace(
                complete_facts(),
                files=("generated/code.py", "generated/tests/test_code.py"),
            ),
            "generated-code-only change",
        ),
        (replace(complete_facts(), lines_changed=2_001), "oversized change"),
        (
            replace(complete_facts(), reproducible_environment=False),
            "unsupported verification environment",
        ),
    ],
)
def test_hard_rejections_are_explained(facts: CandidateFacts, reason: str) -> None:
    assert score_candidate(facts, threshold=70).rejection == reason
