import pytest

from gauntlet_core import evaluate_cycle, validate_contract


def contract(**overrides):
    payload = {
        "name": "teste",
        "goal": "gerar algo",
        "artifact": "out/artefato.md",
        "criteria": [
            {"name": "clareza", "description": "legivel", "gate": 9},
            {"name": "ritmo", "description": "cadencia", "gate": 7, "blocking": False},
        ],
    }
    payload.update(overrides)
    return validate_contract(payload)["contract"]


def workspace(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "artefato.md").write_text("conteudo", encoding="utf-8")
    return tmp_path


def review(**overrides):
    payload = {
        "decision": "approved",
        "coverage": 1.0,
        "criteria": {"clareza": 9, "ritmo": 7},
        "hard_failures": [],
        "feedback": [],
        "artifact": "out/artefato.md",
    }
    payload.update(overrides)
    return payload


def test_approves_when_all_gates_pass(tmp_path):
    result = evaluate_cycle(review(), contract=contract(), cycle=1, workspace_root=workspace(tmp_path))
    assert result["status"] == "approved"
    assert result["human_signoff"] == "pending"
    assert result["artifact_fingerprint"].startswith("sha256:")


def test_blocks_on_structural_review_error(tmp_path):
    result = evaluate_cycle(
        review(decision="talvez"), contract=contract(), cycle=1, workspace_root=workspace(tmp_path)
    )
    assert result["status"] == "blocked"
    assert any("decision" in reason for reason in result["failure_reasons"])


def test_blocks_when_artifact_missing(tmp_path):
    result = evaluate_cycle(review(), contract=contract(), cycle=1, workspace_root=tmp_path)
    assert result["status"] == "blocked"
    assert "artifact does not exist" in result["failure_reasons"]


def test_blocks_when_check_fails(tmp_path):
    payload = contract(checks=[{"name": "ruim", "run": "false"}])
    result = evaluate_cycle(review(), contract=payload, cycle=1, workspace_root=workspace(tmp_path))
    assert result["status"] == "blocked"
    assert result["failure_reasons"] == ["check failed: ruim"]


def test_blocks_on_hard_failure(tmp_path):
    result = evaluate_cycle(
        review(hard_failures=["fonte inventada"]),
        contract=contract(),
        cycle=1,
        workspace_root=workspace(tmp_path),
    )
    assert result["status"] == "blocked"


def test_retries_on_failed_criterion_with_fix(tmp_path):
    result = evaluate_cycle(
        review(
            decision="feedback",
            criteria={"clareza": 8, "ritmo": 7},
            feedback=[{"criterion": "clareza", "fix": "reescrever abertura"}],
        ),
        contract=contract(),
        cycle=1,
        workspace_root=workspace(tmp_path),
    )
    assert result["status"] == "retry"
    assert result["failed_criteria"] == ["clareza"]


def test_blocks_when_fix_missing_for_failed_criterion(tmp_path):
    result = evaluate_cycle(
        review(decision="feedback", criteria={"clareza": 8, "ritmo": 7}),
        contract=contract(),
        cycle=1,
        workspace_root=workspace(tmp_path),
    )
    assert result["status"] == "blocked"


def test_retries_on_coverage_gap_with_matching_fix(tmp_path):
    result = evaluate_cycle(
        review(
            decision="feedback",
            coverage=0.9,
            coverage_gaps=["clareza"],
            feedback=[{"criterion": "clareza", "fix": "cobrir o ponto 3"}],
        ),
        contract=contract(),
        cycle=1,
        workspace_root=workspace(tmp_path),
    )
    assert result["status"] == "retry"


def test_blocks_on_coverage_gap_without_matching_fix(tmp_path):
    result = evaluate_cycle(
        review(decision="feedback", coverage=0.9, coverage_gaps=["clareza"]),
        contract=contract(),
        cycle=1,
        workspace_root=workspace(tmp_path),
    )
    assert result["status"] == "blocked"


def test_non_blocking_criterion_never_blocks(tmp_path):
    result = evaluate_cycle(
        review(criteria={"clareza": 9, "ritmo": 2}),
        contract=contract(),
        cycle=1,
        workspace_root=workspace(tmp_path),
    )
    assert result["status"] == "approved"
    assert result["advisory"] == ["ritmo"]


def test_blocks_at_last_cycle(tmp_path):
    result = evaluate_cycle(
        review(
            decision="feedback",
            criteria={"clareza": 8, "ritmo": 7},
            feedback=[{"criterion": "clareza", "fix": "reescrever"}],
        ),
        contract=contract(max_cycles=2),
        cycle=2,
        workspace_root=workspace(tmp_path),
    )
    assert result["status"] == "blocked"
    assert result["failure_reasons"] == ["quality gates not met"]


def test_rejects_cycle_out_of_range(tmp_path):
    with pytest.raises(ValueError):
        evaluate_cycle(review(), contract=contract(), cycle=6, workspace_root=workspace(tmp_path))
