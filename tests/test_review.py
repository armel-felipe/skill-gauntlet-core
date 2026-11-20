import pytest

from gauntlet_core import validate_contract, validate_review


def contract():
    return validate_contract(
        {
            "name": "teste",
            "goal": "gerar algo",
            "artifact": "out/artefato.md",
            "criteria": [
                {"name": "clareza", "description": "legivel", "gate": 9},
                {"name": "ritmo", "description": "cadencia", "gate": 7, "blocking": False},
            ],
        }
    )["contract"]


def base_review(**overrides):
    review = {
        "decision": "approved",
        "coverage": 1.0,
        "criteria": {"clareza": 9, "ritmo": 7},
        "hard_failures": [],
        "feedback": [],
        "artifact": "out/artefato.md",
    }
    review.update(overrides)
    return review


def test_accepts_valid_review():
    result = validate_review(base_review(), contract())
    assert result["valid"] is True
    assert result["gate_passed"] is True
    assert result["quality_feedback"] == []


def test_rejects_non_object_root():
    result = validate_review([], contract())
    assert result["valid"] is False
    assert result["terminal"] is True


def test_rejects_missing_field():
    review = base_review()
    del review["coverage"]
    assert validate_review(review, contract())["valid"] is False


def test_rejects_unknown_field():
    assert validate_review(base_review(extra=1), contract())["valid"] is False


def test_rejects_bad_decision():
    assert validate_review(base_review(decision="maybe"), contract())["valid"] is False


@pytest.mark.parametrize("coverage", [float("nan"), float("inf"), -0.1, 1.1, "0.9", True])
def test_rejects_invalid_coverage(coverage):
    assert validate_review(base_review(coverage=coverage), contract())["valid"] is False


def test_rejects_criteria_mismatch():
    review = base_review(criteria={"clareza": 9})
    assert validate_review(review, contract())["valid"] is False


def test_rejects_extra_criterion():
    review = base_review(criteria={"clareza": 9, "ritmo": 7, "extra": 10})
    assert validate_review(review, contract())["valid"] is False


def test_rejects_float_score():
    review = base_review(criteria={"clareza": 9.5, "ritmo": 7})
    assert validate_review(review, contract())["valid"] is False


def test_rejects_feedback_without_fix():
    review = base_review(
        decision="feedback",
        criteria={"clareza": 8, "ritmo": 7},
        feedback=[{"criterion": "clareza"}],
    )
    assert validate_review(review, contract())["valid"] is False


def test_rejects_feedback_for_unknown_criterion():
    review = base_review(feedback=[{"criterion": "inexistente", "fix": "x"}])
    assert validate_review(review, contract())["valid"] is False


def test_rejects_artifact_mismatch():
    assert validate_review(base_review(artifact="out/outro.md"), contract())["valid"] is False


def test_lists_blocking_and_advisory_failures():
    review = base_review(
        decision="feedback",
        criteria={"clareza": 8, "ritmo": 6},
        feedback=[
            {"criterion": "clareza", "fix": "reescrever abertura"},
            {"criterion": "ritmo", "kind": "optional_suggestion", "fix": "encurtar frases"},
        ],
    )
    result = validate_review(review, contract())
    assert result["valid"] is True
    assert result["quality_feedback"] == ["clareza"]
    assert result["advisory"] == ["ritmo"]
    assert result["gate_passed"] is False
