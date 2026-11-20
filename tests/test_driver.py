import json

import pytest

from gauntlet_core import run_gauntlet, validate_contract


def contract(**overrides):
    payload = {
        "name": "teste",
        "goal": "gerar algo",
        "artifact": "out/artefato.md",
        "criteria": [{"name": "clareza", "description": "legivel", "gate": 9}],
        "persistence_dir": "runs/teste",
        "run_id": "run-1",
    }
    payload.update(overrides)
    return validate_contract(payload)["contract"]


def workspace(tmp_path):
    (tmp_path / "out").mkdir()
    return tmp_path


def retry_review():
    return {
        "decision": "feedback",
        "coverage": 1.0,
        "criteria": {"clareza": 8},
        "hard_failures": [],
        "feedback": [{"criterion": "clareza", "fix": "reescrever"}],
        "artifact": "out/artefato.md",
    }


def approved_review():
    return {
        "decision": "approved",
        "coverage": 1.0,
        "criteria": {"clareza": 9},
        "hard_failures": [],
        "feedback": [],
        "artifact": "out/artefato.md",
    }


def test_runs_until_approved(tmp_path):
    root = workspace(tmp_path)
    calls = {"executor": 0, "reviewer": 0, "received": []}

    def executor(feedback):
        calls["executor"] += 1
        calls["received"].append(feedback)
        (root / "out" / "artefato.md").write_text("conteudo", encoding="utf-8")

    def reviewer(artifact, feedback):
        calls["reviewer"] += 1
        return retry_review() if calls["reviewer"] == 1 else approved_review()

    result = run_gauntlet(executor, reviewer, contract(), workspace_root=root)
    assert result["status"] == "approved"
    assert result["cycle_count"] == 2
    assert calls["executor"] == 2
    assert calls["received"][0] == []
    assert calls["received"][1][0]["criterion"] == "clareza"


def test_blocks_after_max_cycles(tmp_path):
    root = workspace(tmp_path)

    def executor(feedback):
        (root / "out" / "artefato.md").write_text("conteudo", encoding="utf-8")

    def reviewer(artifact, feedback):
        return retry_review()

    result = run_gauntlet(executor, reviewer, contract(max_cycles=2), workspace_root=root)
    assert result["status"] == "blocked"
    assert result["cycle_count"] == 2
    assert result["failed_criteria"] == ["clareza"]


def test_does_not_rerun_approved_run(tmp_path):
    root = workspace(tmp_path)

    def executor(feedback):
        (root / "out" / "artefato.md").write_text("conteudo", encoding="utf-8")

    def reviewer(artifact, feedback):
        return approved_review()

    first = run_gauntlet(executor, reviewer, contract(), workspace_root=root)

    def failing_executor(feedback):
        raise AssertionError("nao deveria rodar")

    second = run_gauntlet(failing_executor, reviewer, contract(), workspace_root=root)
    assert second == first


def test_resumes_from_retry_cycle(tmp_path):
    root = workspace(tmp_path)
    from gauntlet_core import record_cycle

    (root / "out" / "artefato.md").write_text("conteudo", encoding="utf-8")
    record_cycle(retry_review(), contract=contract(), cycle=1, workspace_root=root)

    calls = {"executor": 0}

    def executor(feedback):
        calls["executor"] += 1
        assert feedback[0]["criterion"] == "clareza"

    def reviewer(artifact, feedback):
        return approved_review()

    result = run_gauntlet(executor, reviewer, contract(), workspace_root=root)
    assert result["status"] == "approved"
    assert result["cycle_count"] == 2
    assert calls["executor"] == 1


def test_rejects_inconsistent_journal(tmp_path):
    root = workspace(tmp_path)
    directory = root / "runs" / "teste"
    directory.mkdir(parents=True)
    (directory / "cycle-01.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        run_gauntlet(lambda feedback: None, lambda artifact, feedback: approved_review(),
                     contract(), workspace_root=root)


def test_raises_on_invalid_contract():
    with pytest.raises(ValueError):
        run_gauntlet(lambda feedback: None, lambda artifact, feedback: {}, {"name": "x"})


def test_rejects_cycle_file_out_of_sequence(tmp_path):
    root = workspace(tmp_path)
    directory = root / "runs" / "teste"
    directory.mkdir(parents=True)
    (directory / "cycle-03.json").write_text(
        json.dumps(
            {
                "idempotency_key": ["run-1", "out/artefato.md", 1],
                "review": retry_review(),
            }
        ),
        encoding="utf-8",
    )
    (directory / "events.json").write_text(
        json.dumps(
            [
                {"cycle": 1, "event": "cycle-start", "artifact": "out/artefato.md"},
                {"cycle": 1, "event": "deterministic-checks", "results": []},
                {"cycle": 1, "event": "review", "review": retry_review()},
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="out of sequence"):
        run_gauntlet(lambda feedback: None, lambda artifact, feedback: approved_review(),
                     contract(), workspace_root=root)


def test_rejects_wrong_event_events(tmp_path):
    root = workspace(tmp_path)
    directory = root / "runs" / "teste"
    directory.mkdir(parents=True)
    (directory / "cycle-01.json").write_text(
        json.dumps(
            {
                "idempotency_key": ["run-1", "out/artefato.md", 1],
                "review": retry_review(),
            }
        ),
        encoding="utf-8",
    )
    (directory / "events.json").write_text(
        json.dumps(
            [
                {"cycle": 1, "event": "cycle-start", "artifact": "out/artefato.md"},
                {"cycle": 1, "event": "review", "review": retry_review()},
                {"cycle": 1, "event": "review", "review": retry_review()},
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="events are incomplete"):
        run_gauntlet(lambda feedback: None, lambda artifact, feedback: approved_review(),
                     contract(), workspace_root=root)
