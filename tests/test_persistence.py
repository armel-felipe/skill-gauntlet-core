import json

import pytest

from gauntlet_core import record_cycle, validate_contract


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
    (tmp_path / "out" / "artefato.md").write_text("conteudo", encoding="utf-8")
    return tmp_path


def review(**overrides):
    payload = {
        "decision": "approved",
        "coverage": 1.0,
        "criteria": {"clareza": 9},
        "hard_failures": [],
        "feedback": [],
        "artifact": "out/artefato.md",
    }
    payload.update(overrides)
    return payload


def retry_review():
    return review(
        decision="feedback",
        criteria={"clareza": 8},
        feedback=[{"criterion": "clareza", "fix": "reescrever"}],
    )


def test_writes_cycle_events_and_state(tmp_path):
    root = workspace(tmp_path)
    result = record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)
    assert result["status"] == "approved"
    directory = root / "runs" / "teste" / "run-1"
    assert json.loads((directory / "cycle-01.json").read_text())["idempotency_key"] == [
        "run-1",
        "out/artefato.md",
        1,
    ]
    events = json.loads((directory / "events.json").read_text())
    assert [event["event"] for event in events] == [
        "cycle-start",
        "deterministic-checks",
        "review",
    ]
    state = json.loads((directory / "state.json").read_text())
    assert state["status"] == "approved"
    assert state["human_signoff"] == "pending"


def test_no_journal_without_persistence_dir(tmp_path):
    root = workspace(tmp_path)
    record_cycle(review(), contract=contract(persistence_dir=None), cycle=1, workspace_root=root)
    assert not (root / "runs").exists()


def test_repeating_same_cycle_is_noop(tmp_path):
    root = workspace(tmp_path)
    record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)
    first = (root / "runs" / "teste" / "run-1" / "cycle-01.json").read_text()
    record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)
    assert (root / "runs" / "teste" / "run-1" / "cycle-01.json").read_text() == first


def test_same_cycle_different_content_is_error(tmp_path):
    root = workspace(tmp_path)
    record_cycle(retry_review(), contract=contract(), cycle=1, workspace_root=root)
    with pytest.raises(ValueError, match="already recorded"):
        record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)


def test_rejects_terminal_journal(tmp_path):
    root = workspace(tmp_path)
    record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)
    with pytest.raises(ValueError, match="terminal"):
        record_cycle(retry_review(), contract=contract(), cycle=2, workspace_root=root)


def test_rejects_gap_in_history(tmp_path):
    root = workspace(tmp_path)
    with pytest.raises(ValueError, match="incomplete"):
        record_cycle(retry_review(), contract=contract(), cycle=2, workspace_root=root)


def test_rejects_symlink_in_journal(tmp_path):
    root = workspace(tmp_path)
    directory = root / "runs" / "teste" / "run-1"
    directory.mkdir(parents=True)
    (directory / "state.json").symlink_to(root / "out" / "artefato.md")
    with pytest.raises(ValueError):
        record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)


def test_rejects_symlinked_cycle_file(tmp_path):
    root = workspace(tmp_path)
    record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)
    directory = root / "runs" / "teste" / "run-1"
    stored = directory / "cycle-01.json"
    outside = root / "outside.json"
    outside.write_text(stored.read_text(encoding="utf-8"), encoding="utf-8")
    stored.unlink()
    stored.symlink_to(outside)
    with pytest.raises(ValueError):
        record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)


def test_rejects_symlinked_persistence_dir(tmp_path):
    root = workspace(tmp_path)
    real = tmp_path / "real-journal"
    real.mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "teste").symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)


def test_rejects_non_list_events(tmp_path):
    root = workspace(tmp_path)
    directory = root / "runs" / "teste" / "run-1"
    directory.mkdir(parents=True)
    (directory / "events.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="not a list"):
        record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)


def test_fast_path_requires_events(tmp_path):
    root = workspace(tmp_path)
    record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)
    (root / "runs" / "teste" / "run-1" / "events.json").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)


def test_persistence_failure_returns_blocked(tmp_path):
    root = workspace(tmp_path)
    (root / "runs").write_text("nao e diretorio", encoding="utf-8")
    result = record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)
    assert result["status"] == "blocked"
    assert result["failure_reasons"][0].startswith("persistence failed")


def test_rejects_forged_cycle_file(tmp_path):
    root = workspace(tmp_path)
    directory = root / "runs" / "teste" / "run-1"
    directory.mkdir(parents=True)
    (directory / "cycle-99.json").write_text("{}", encoding="utf-8")
    (directory / "events.json").write_text(json.dumps([{}, {}, {}]), encoding="utf-8")
    with pytest.raises(ValueError):
        record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)
