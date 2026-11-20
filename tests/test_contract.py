import json

import pytest

from gauntlet_core import load_contract, validate_contract


def base_contract(**overrides):
    contract = {
        "name": "teste",
        "goal": "gerar algo",
        "artifact": "out/artefato.md",
        "criteria": [{"name": "clareza", "description": "legivel", "gate": 9}],
    }
    contract.update(overrides)
    return contract


def test_applies_defaults():
    result = validate_contract(base_contract())
    assert result["valid"] is True
    contract = result["contract"]
    assert contract["coverage_gate"] == 0.99
    assert contract["max_cycles"] == 5
    assert contract["checks"] == []
    assert contract["run_id"] == "run"
    assert contract["persistence_dir"] is None
    assert contract["criteria"][0]["blocking"] is True


def test_rejects_absolute_artifact():
    result = validate_contract(base_contract(artifact="/tmp/artefato.md"))
    assert result["valid"] is False
    assert any("artifact" in error for error in result["errors"])


def test_rejects_artifact_escaping_workspace():
    result = validate_contract(base_contract(artifact="../fora/artefato.md"))
    assert result["valid"] is False


@pytest.mark.parametrize("gate", [0, 11, True, 9.5, "9"])
def test_rejects_invalid_gate(gate):
    contract = base_contract(criteria=[{"name": "clareza", "description": "legivel", "gate": gate}])
    assert validate_contract(contract)["valid"] is False


def test_requires_one_blocking_criterion():
    contract = base_contract(
        criteria=[{"name": "ritmo", "description": "cadencia", "gate": 7, "blocking": False}]
    )
    result = validate_contract(contract)
    assert result["valid"] is False
    assert any("blocking" in error for error in result["errors"])


def test_rejects_unknown_field():
    assert validate_contract(base_contract(extra=1))["valid"] is False


def test_rejects_duplicate_criterion_name():
    contract = base_contract(
        criteria=[
            {"name": "clareza", "description": "a"},
            {"name": "clareza", "description": "b"},
        ]
    )
    assert validate_contract(contract)["valid"] is False


def test_rejects_max_cycles_six():
    assert validate_contract(base_contract(max_cycles=6))["valid"] is False


def test_rejects_invalid_check_timeout():
    contract = base_contract(checks=[{"name": "ok", "run": "true", "timeout_s": 0}])
    assert validate_contract(contract)["valid"] is False


def test_load_contract_reads_and_validates(tmp_path):
    path = tmp_path / "contrato.json"
    path.write_text(json.dumps(base_contract()), encoding="utf-8")
    contract = load_contract(path)
    assert contract["name"] == "teste"
    assert contract["artifact"] == "out/artefato.md"


def test_load_contract_raises_on_invalid_json(tmp_path):
    path = tmp_path / "contrato.json"
    path.write_text("{nao e json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_contract(path)


@pytest.mark.parametrize("artifact", ["C:\\tmp\\artefato.md", "out\\..\\..\\x.md"])
def test_rejects_windows_style_artifact_escape(artifact):
    assert validate_contract(base_contract(artifact=artifact))["valid"] is False


def test_rejects_unknown_criterion_field():
    contract = base_contract(
        criteria=[{"name": "clareza", "description": "legivel", "extra": 1}]
    )
    result = validate_contract(contract)
    assert result["valid"] is False
    assert any("criteria[0]" in error and "unknown" in error for error in result["errors"])


def test_rejects_unknown_check_field():
    contract = base_contract(checks=[{"name": "ok", "run": "true", "extra": 1}])
    result = validate_contract(contract)
    assert result["valid"] is False
    assert any("checks[0]" in error and "unknown" in error for error in result["errors"])


@pytest.mark.parametrize("coverage_gate", [0.4, 1.1, True])
def test_rejects_invalid_coverage_gate(coverage_gate):
    assert validate_contract(base_contract(coverage_gate=coverage_gate))["valid"] is False


def test_rejects_persistence_dir_traversal():
    result = validate_contract(base_contract(persistence_dir="../fora"))
    assert result["valid"] is False
    assert any("persistence_dir" in error for error in result["errors"])


def test_rejects_blank_run_id():
    assert validate_contract(base_contract(run_id="  "))["valid"] is False


def test_normalized_key_sets():
    contract = base_contract(checks=[{"name": "ok", "run": "true"}])
    result = validate_contract(contract)
    assert result["valid"] is True
    normalized = result["contract"]
    assert set(normalized) == {
        "name",
        "goal",
        "artifact",
        "criteria",
        "coverage_gate",
        "max_cycles",
        "checks",
        "persistence_dir",
        "run_id",
    }
    assert set(normalized["criteria"][0]) == {"name", "description", "gate", "blocking"}
    assert set(normalized["checks"][0]) == {"name", "run", "timeout_s"}


def test_default_gate_is_nine():
    contract = base_contract(criteria=[{"name": "clareza", "description": "legivel"}])
    result = validate_contract(contract)
    assert result["valid"] is True
    assert result["contract"]["criteria"][0]["gate"] == 9


def test_load_contract_rejects_yaml(tmp_path):
    path = tmp_path / "contrato.yaml"
    path.write_text(
        "name: teste\ngoal: gerar algo\nartifact: out/artefato.md\ncriteria:\n  - name: clareza\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not valid JSON"):
        load_contract(path)
