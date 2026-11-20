# Gauntlet Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar a skill global `gauntlet-core`: motor Python genérico que roda ciclos executor→checks→revisor→gates a partir de um contrato JSON de critérios de qualidade, com `approved`/`blocked` fail-closed e diário auditável.

**Architecture:** Um único módulo `gauntlet_core.py` (stdlib, sem CLI) expõe validação de contrato, validação de review, checks determinísticos, avaliação de gates, persistência idempotente e o driver de ciclos. `SKILL.md` ensina o agente a capturar critérios no contrato e a conduzir os ciclos com `task` isoladas. O repo publica cópias auto-contidas para agents, Claude e OpenCode.

**Tech Stack:** Python 3.9+, `json`, `subprocess`, `pathlib`, `tempfile`, `hashlib`, `pytest`.

**Spec:** `docs/specs/2026-11-20-gauntlet-core-design.md`

## Global Constraints

- Python 3.9+; apenas stdlib no motor. `pytest` é dependência de desenvolvimento.
- Contrato e diário são JSON. YAML não é aceito em nenhuma entrada.
- Sem CLI: a API pública é `load_contract`, `validate_contract`, `validate_review`, `run_checks`, `evaluate_cycle`, `record_cycle`, `run_gauntlet`.
- `gate` inteiro 1–10 (default 9); `coverage_gate` 0.5–1.0 (default 0.99); `max_cycles` inteiro 1–5 (default 5). Sexto ciclo nunca acontece.
- `approved` sempre inclui `"human_signoff": "pending"`; o motor nunca declara aprovação humana.
- Campo desconhecido em contrato, critério, check, review ou feedback é erro estrutural.
- Cópias em `agents/skills/gauntlet-core/`, `.claude/skills/gauntlet-core/` e `opencode/skills/gauntlet-core/` são byte-idênticas ao canônico e geradas por `scripts/build-harness-copies.sh`.
- Licença MIT. Repositório `skill-gauntlet-core` (prefixo obrigatório da skill de publicação).
- Nomes de arquivos de diário: `cycle-01.json` … `cycle-05.json`, `events.json`, `state.json`.

---

## File Structure

```
skill-gauntlet-core/
├── SKILL.md
├── README.md
├── LICENSE
├── gauntlet_core.py
├── contracts/
│   ├── contrato-editorial.json
│   └── contrato-codigo.json
├── examples/
│   └── diario-exemplo/
│       ├── cycle-01.json
│       ├── events.json
│       └── state.json
├── tests/
│   ├── test_contract.py
│   ├── test_review.py
│   ├── test_checks.py
│   ├── test_gates.py
│   ├── test_persistence.py
│   ├── test_driver.py
│   └── test_harness_copies.py
├── scripts/
│   └── build-harness-copies.sh
├── agents/skills/gauntlet-core/
├── .claude/skills/gauntlet-core/
└── opencode/skills/gauntlet-core/
```

---

### Task 1: Scaffold do repo e validação de contrato

**Files:**
- Create: `gauntlet_core.py`
- Create: `tests/test_contract.py`
- Create: `pytest.ini`
- Create: `.gitignore`

**Interfaces:**
- Produces: `validate_contract(contract) -> {"valid": bool, "errors": list[str], "contract": dict | None}` e `load_contract(path) -> dict`. O contrato normalizado tem as chaves `name`, `goal`, `artifact`, `criteria`, `coverage_gate`, `max_cycles`, `checks`, `persistence_dir`, `run_id`; cada critério normalizado tem `name`, `description`, `gate`, `blocking`; cada check tem `name`, `run`, `timeout_s`.

- [ ] **Step 1: Criar scaffold mínimo do repo**

```bash
cd "/Users/mac/llm server/projetos/skill-gauntlet-core"
printf '[pytest]\ntestpaths = tests\n' > pytest.ini
printf '__pycache__/\n*.pyc\n.pytest_cache/\n' > .gitignore
mkdir -p tests contracts examples/diario-exemplo scripts
```

- [ ] **Step 2: Escrever os testes de contrato**

`tests/test_contract.py`:

```python
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
```

- [ ] **Step 3: Rodar os testes para ver falhar**

Run: `pytest tests/test_contract.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'gauntlet_core'`

- [ ] **Step 4: Implementar constantes, helpers e validação de contrato**

`gauntlet_core.py`:

```python
"""Motor generico do Gauntlet: contrato de qualidade -> ciclos -> approved/blocked."""

import json
import math
import os
from copy import deepcopy
from hashlib import sha256
from numbers import Real
from pathlib import Path

CONTRACT_REQUIRED = {"name", "goal", "artifact", "criteria"}
CONTRACT_OPTIONAL = {"coverage_gate", "max_cycles", "checks", "persistence_dir", "run_id"}
CRITERION_REQUIRED = {"name", "description"}
CRITERION_OPTIONAL = {"gate", "blocking"}
CHECK_REQUIRED = {"name", "run"}
CHECK_OPTIONAL = {"timeout_s"}
DEFAULT_GATE = 9
DEFAULT_COVERAGE_GATE = 0.99
DEFAULT_MAX_CYCLES = 5
DEFAULT_TIMEOUT_S = 60
MAX_CYCLES = 5


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _finite(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _relative_error(value):
    if not isinstance(value, str) or not value.strip():
        return "must be a non-empty string"
    if os.path.isabs(value):
        return "must be relative to the workspace"
    if ".." in Path(value).parts:
        return "must not escape the workspace"
    return None


def validate_contract(contract):
    errors = []
    if not isinstance(contract, dict):
        return {"valid": False, "errors": ["contract root must be an object"], "contract": None}

    unknown = set(contract) - CONTRACT_REQUIRED - CONTRACT_OPTIONAL
    if unknown:
        errors.append(f"unknown contract fields: {sorted(unknown)}")
    missing = CONTRACT_REQUIRED - set(contract)
    if missing:
        errors.append(f"missing contract fields: {sorted(missing)}")

    name = contract.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name must be a non-empty string")

    goal = contract.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        errors.append("goal must be a non-empty string")

    artifact = contract.get("artifact")
    artifact_error = _relative_error(artifact)
    if artifact_error:
        errors.append(f"artifact {artifact_error}")

    criteria = []
    values = contract.get("criteria")
    if not isinstance(values, list) or not values:
        errors.append("criteria must be a non-empty list")
        values = []
    seen = set()
    for index, item in enumerate(values):
        prefix = f"criteria[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        unknown = set(item) - CRITERION_REQUIRED - CRITERION_OPTIONAL
        if unknown:
            errors.append(f"{prefix} has unknown fields: {sorted(unknown)}")
        missing = CRITERION_REQUIRED - set(item)
        if missing:
            errors.append(f"{prefix} missing fields: {sorted(missing)}")
        item_name = item.get("name")
        if not isinstance(item_name, str) or not item_name.strip():
            errors.append(f"{prefix}.name must be a non-empty string")
        elif item_name in seen:
            errors.append(f"{prefix}.name duplicated: {item_name}")
        else:
            seen.add(item_name)
        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{prefix}.description must be a non-empty string")
        gate = item.get("gate", DEFAULT_GATE)
        if not _is_int(gate) or not 1 <= gate <= 10:
            errors.append(f"{prefix}.gate must be an integer between 1 and 10")
        blocking = item.get("blocking", True)
        if not isinstance(blocking, bool):
            errors.append(f"{prefix}.blocking must be a boolean")
        criteria.append(
            {"name": item_name, "description": description, "gate": gate, "blocking": blocking}
        )
    if values and not any(criterion["blocking"] for criterion in criteria):
        errors.append("at least one criterion must be blocking")

    coverage_gate = contract.get("coverage_gate", DEFAULT_COVERAGE_GATE)
    if not _finite(coverage_gate) or not 0.5 <= coverage_gate <= 1.0:
        errors.append("coverage_gate must be a number between 0.5 and 1.0")

    max_cycles = contract.get("max_cycles", DEFAULT_MAX_CYCLES)
    if not _is_int(max_cycles) or not 1 <= max_cycles <= MAX_CYCLES:
        errors.append("max_cycles must be an integer between 1 and 5")

    checks = []
    check_values = contract.get("checks", [])
    if not isinstance(check_values, list):
        errors.append("checks must be a list")
        check_values = []
    for index, item in enumerate(check_values):
        prefix = f"checks[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        unknown = set(item) - CHECK_REQUIRED - CHECK_OPTIONAL
        if unknown:
            errors.append(f"{prefix} has unknown fields: {sorted(unknown)}")
        missing = CHECK_REQUIRED - set(item)
        if missing:
            errors.append(f"{prefix} missing fields: {sorted(missing)}")
        check_name = item.get("name")
        if not isinstance(check_name, str) or not check_name.strip():
            errors.append(f"{prefix}.name must be a non-empty string")
        command = item.get("run")
        if not isinstance(command, str) or not command.strip():
            errors.append(f"{prefix}.run must be a non-empty string")
        timeout_s = item.get("timeout_s", DEFAULT_TIMEOUT_S)
        if not _is_int(timeout_s) or not 1 <= timeout_s <= 600:
            errors.append(f"{prefix}.timeout_s must be an integer between 1 and 600")
        checks.append({"name": check_name, "run": command, "timeout_s": timeout_s})

    persistence_dir = contract.get("persistence_dir")
    if persistence_dir is not None:
        persistence_error = _relative_error(persistence_dir)
        if persistence_error:
            errors.append(f"persistence_dir {persistence_error}")

    run_id = contract.get("run_id", "run")
    if not isinstance(run_id, str) or not run_id.strip():
        errors.append("run_id must be a non-empty string")

    if errors:
        return {"valid": False, "errors": errors, "contract": None}

    normalized = {
        "name": name,
        "goal": goal,
        "artifact": artifact,
        "criteria": criteria,
        "coverage_gate": coverage_gate,
        "max_cycles": max_cycles,
        "checks": checks,
        "persistence_dir": persistence_dir,
        "run_id": run_id,
    }
    return {"valid": True, "errors": [], "contract": normalized}


def load_contract(path):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"contract not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"contract is not valid JSON: {error}") from error
    result = validate_contract(raw)
    if not result["valid"]:
        raise ValueError("; ".join(result["errors"]))
    return result["contract"]
```

- [ ] **Step 5: Rodar os testes e ver passar**

Run: `pytest tests/test_contract.py -q`
Expected: `15 passed`

- [ ] **Step 6: Commit**

```bash
git add gauntlet_core.py tests/test_contract.py pytest.ini .gitignore
git commit -m "feat: validacao de contrato do gauntlet-core"
```

---

### Task 2: Validação de review

**Files:**
- Modify: `gauntlet_core.py` (adiciona constantes e `validate_review`)
- Create: `tests/test_review.py`

**Interfaces:**
- Consumes: contrato normalizado da Task 1.
- Produces: `validate_review(review, contract) -> {"valid", "terminal", "errors", "quality_feedback", "advisory", "gate_passed"}`. `quality_feedback` lista critérios bloqueantes abaixo do gate; `advisory` lista critérios não bloqueantes abaixo do gate.

- [ ] **Step 1: Escrever os testes de review**

`tests/test_review.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_review.py -q`
Expected: FAIL com `ImportError: cannot import name 'validate_review'`

- [ ] **Step 3: Implementar `validate_review`**

Adicionar ao topo de `gauntlet_core.py`, junto das constantes:

```python
REVIEW_REQUIRED = {"decision", "coverage", "criteria", "hard_failures", "feedback", "artifact"}
REVIEW_OPTIONAL = {"coverage_gaps"}
FEEDBACK_KEYS = {"criterion", "kind", "fix"}
DECISIONS = {"approved", "feedback"}
KINDS = {"required_fix", "optional_suggestion"}
```

Adicionar a função ao final do módulo:

```python
def validate_review(review, contract):
    gates = {criterion["name"]: criterion for criterion in contract["criteria"]}
    result = {"valid": False, "terminal": True, "errors": [], "quality_feedback": [],
              "advisory": [], "gate_passed": False}
    if not isinstance(review, dict):
        result["errors"] = ["review root must be an object"]
        return result

    errors = []
    unknown = set(review) - REVIEW_REQUIRED - REVIEW_OPTIONAL
    if unknown:
        errors.append(f"unknown review fields: {sorted(unknown)}")
    missing = REVIEW_REQUIRED - set(review)
    if missing:
        errors.append(f"missing review fields: {sorted(missing)}")

    decision = review.get("decision")
    if decision not in DECISIONS:
        errors.append("decision must be approved or feedback")

    coverage = review.get("coverage")
    if not _finite(coverage) or not 0 <= coverage <= 1:
        errors.append("coverage must be a finite number between 0 and 1")

    scores = review.get("criteria")
    if not isinstance(scores, dict):
        errors.append("criteria must be an object")
        scores = {}
    elif set(scores) != set(gates):
        errors.append("criteria must match the contract criteria exactly")
    for item_name, value in scores.items():
        if not _is_int(value) or not 0 <= value <= 10:
            errors.append(f"criteria.{item_name} must be an integer between 0 and 10")

    hard_failures = review.get("hard_failures")
    if not isinstance(hard_failures, list) or not all(
        isinstance(item, str) and item.strip() for item in hard_failures
    ):
        errors.append("hard_failures must be a list of non-empty strings")
        hard_failures = []

    feedback = review.get("feedback")
    if not isinstance(feedback, list):
        errors.append("feedback must be a list")
        feedback = []
    for index, item in enumerate(feedback):
        prefix = f"feedback[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        unknown = set(item) - FEEDBACK_KEYS
        if unknown:
            errors.append(f"{prefix} has unknown fields: {sorted(unknown)}")
        if item.get("criterion") not in gates:
            errors.append(f"{prefix}.criterion must be one of the contract criteria")
        if item.get("kind", "required_fix") not in KINDS:
            errors.append(f"{prefix}.kind must be required_fix or optional_suggestion")
        fix = item.get("fix")
        if not isinstance(fix, str) or not fix.strip():
            errors.append(f"{prefix}.fix must be a non-empty string")

    gaps = review.get("coverage_gaps", [])
    if not isinstance(gaps, list) or not all(gap in gates for gap in gaps):
        errors.append("coverage_gaps must be a list of contract criteria")

    artifact = review.get("artifact")
    if not isinstance(artifact, str) or not artifact.strip():
        errors.append("artifact must be a non-empty string")
    elif artifact != contract["artifact"]:
        errors.append("artifact must match the contract artifact")

    quality_feedback = []
    advisory = []
    if not errors:
        for item_name, criterion in gates.items():
            if scores[item_name] < criterion["gate"]:
                target = quality_feedback if criterion["blocking"] else advisory
                target.append(item_name)
    gate_passed = (
        not errors
        and not quality_feedback
        and not hard_failures
        and _finite(coverage)
        and coverage >= contract["coverage_gate"]
    )
    return {
        "valid": not errors,
        "terminal": bool(errors),
        "errors": errors,
        "quality_feedback": sorted(quality_feedback),
        "advisory": sorted(advisory),
        "gate_passed": gate_passed,
    }
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_review.py tests/test_contract.py -q`
Expected: `33 passed`

- [ ] **Step 5: Commit**

```bash
git add gauntlet_core.py tests/test_review.py
git commit -m "feat: validacao de review do gauntlet-core"
```

---

### Task 3: Checks estruturais e comandos determinísticos

**Files:**
- Modify: `gauntlet_core.py` (adiciona `_artifact_errors` e `run_checks`)
- Create: `tests/test_checks.py`

**Interfaces:**
- Produces: `run_checks(contract, workspace_root=None) -> list[{"name", "status", "exit_code", "output"}]` com `status` ∈ `pass|fail|error`.
- Produces: `_artifact_errors(root: Path, artifact: str) -> list[str]` (uso interno, mas testado diretamente).

- [ ] **Step 1: Escrever os testes**

`tests/test_checks.py`:

```python
from pathlib import Path

from gauntlet_core import _artifact_errors, run_checks, validate_contract


def contract(**overrides):
    payload = {
        "name": "teste",
        "goal": "gerar algo",
        "artifact": "out/artefato.md",
        "criteria": [{"name": "clareza", "description": "legivel"}],
    }
    payload.update(overrides)
    return validate_contract(payload)["contract"]


def test_artifact_errors_empty_when_file_exists(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "artefato.md").write_text("conteudo", encoding="utf-8")
    assert _artifact_errors(tmp_path, "out/artefato.md") == []


def test_artifact_errors_missing(tmp_path):
    assert "artifact does not exist" in _artifact_errors(tmp_path, "out/artefato.md")


def test_artifact_errors_empty_file(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "artefato.md").write_text("", encoding="utf-8")
    assert "artifact is empty" in _artifact_errors(tmp_path, "out/artefato.md")


def test_artifact_errors_symlink(tmp_path):
    (tmp_path / "out").mkdir()
    target = tmp_path / "out" / "real.md"
    target.write_text("conteudo", encoding="utf-8")
    (tmp_path / "out" / "artefato.md").symlink_to(target)
    assert "artifact must not be a symlink" in _artifact_errors(tmp_path, "out/artefato.md")


def test_artifact_errors_directory(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "artefato.md").mkdir()
    assert "artifact must be a regular file" in _artifact_errors(tmp_path, "out/artefato.md")


def test_run_checks_pass(tmp_path):
    results = run_checks(contract(checks=[{"name": "ok", "run": "true"}]), tmp_path)
    assert results[0]["status"] == "pass"
    assert results[0]["exit_code"] == 0


def test_run_checks_fail(tmp_path):
    results = run_checks(contract(checks=[{"name": "ruim", "run": "false"}]), tmp_path)
    assert results[0]["status"] == "fail"
    assert results[0]["exit_code"] == 1


def test_run_checks_error_on_timeout(tmp_path):
    payload = contract(checks=[{"name": "lento", "run": "sleep 5", "timeout_s": 1}])
    results = run_checks(payload, tmp_path)
    assert results[0]["status"] == "error"
    assert "timeout" in results[0]["output"]


def test_run_checks_runs_inside_workspace(tmp_path):
    (tmp_path / "marca.txt").write_text("ok", encoding="utf-8")
    results = run_checks(
        contract(checks=[{"name": "cwd", "run": "test -f marca.txt"}]), tmp_path
    )
    assert results[0]["status"] == "pass"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_checks.py -q`
Expected: FAIL com `ImportError: cannot import name '_artifact_errors'`

- [ ] **Step 3: Implementar**

Adicionar import no topo:

```python
import subprocess
```

Adicionar as funções ao final de `gauntlet_core.py`:

```python
def _artifact_errors(root, artifact):
    path = root / artifact
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return ["artifact escapes the workspace"]
    errors = []
    if path.is_symlink():
        errors.append("artifact must not be a symlink")
    if not resolved.exists():
        errors.append("artifact does not exist")
    elif not resolved.is_file():
        errors.append("artifact must be a regular file")
    else:
        try:
            size = resolved.stat().st_size
        except OSError as error:
            errors.append(f"artifact is not readable: {error}")
        else:
            if size == 0:
                errors.append("artifact is empty")
    return errors


def run_checks(contract, workspace_root=None):
    root = Path.cwd().resolve() if workspace_root is None else Path(workspace_root).resolve()
    results = []
    for check in contract["checks"]:
        try:
            completed = subprocess.run(
                check["run"],
                shell=True,
                cwd=str(root),
                text=True,
                capture_output=True,
                timeout=check["timeout_s"],
            )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "name": check["name"],
                    "status": "error",
                    "exit_code": None,
                    "output": f"timeout after {check['timeout_s']}s",
                }
            )
            continue
        except OSError as error:
            results.append(
                {"name": check["name"], "status": "error", "exit_code": None, "output": str(error)}
            )
            continue
        output = (completed.stdout or "") + (completed.stderr or "")
        results.append(
            {
                "name": check["name"],
                "status": "pass" if completed.returncode == 0 else "fail",
                "exit_code": completed.returncode,
                "output": output.strip()[:2000],
            }
        )
    return results
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_checks.py -q`
Expected: `9 passed` (o teste de timeout pode levar ~1s)

- [ ] **Step 5: Commit**

```bash
git add gauntlet_core.py tests/test_checks.py
git commit -m "feat: checks estruturais e comandos do gauntlet-core"
```

---

### Task 4: Gates e avaliação de ciclo

**Files:**
- Modify: `gauntlet_core.py` (adiciona `_blocked_cycle` e `evaluate_cycle`)
- Create: `tests/test_gates.py`

**Interfaces:**
- Consumes: `validate_review`, `_artifact_errors`, `run_checks`.
- Produces: `evaluate_cycle(review, *, contract, cycle, workspace_root=None) -> dict` puro, sem escrita. Retorno tem `status` ∈ `approved|blocked|retry`, `cycle_count`, `last_review`, `checks`; `retry` traz `feedback`, `failed_criteria`, `advisory`; `blocked` traz `failure_reasons`, `failed_criteria`, `last_artifact`; `approved` traz `last_artifact`, `artifact_fingerprint`, `human_signoff: "pending"`, `advisory`.

- [ ] **Step 1: Escrever os testes de gates**

`tests/test_gates.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_gates.py -q`
Expected: FAIL com `ImportError: cannot import name 'evaluate_cycle'`

- [ ] **Step 3: Implementar**

Adicionar a `gauntlet_core.py`:

```python
def _blocked_cycle(cycle, reasons, artifact, review, failed_criteria, checks=None):
    feedback = review.get("feedback", []) if isinstance(review, dict) else []
    return {
        "status": "blocked",
        "cycle_count": cycle,
        "failure_reasons": list(reasons),
        "failed_criteria": sorted(failed_criteria),
        "last_artifact": artifact,
        "last_review": deepcopy(review),
        "feedback": deepcopy(feedback),
        "checks": checks or [],
    }


def evaluate_cycle(review, *, contract, cycle, workspace_root=None):
    root = Path.cwd().resolve() if workspace_root is None else Path(workspace_root).resolve()
    if not _is_int(cycle) or not 1 <= cycle <= contract["max_cycles"]:
        raise ValueError("cycle must be an integer within max_cycles")

    validation = validate_review(review, contract)
    if not validation["valid"]:
        return _blocked_cycle(cycle, validation["errors"], contract["artifact"], review, [])

    artifact_errors = _artifact_errors(root, contract["artifact"])
    if artifact_errors:
        return _blocked_cycle(cycle, artifact_errors, contract["artifact"], review, [])

    checks = run_checks(contract, root)
    failed_checks = [
        f"check failed: {item['name']}" for item in checks if item["status"] != "pass"
    ]
    if failed_checks:
        return _blocked_cycle(
            cycle, failed_checks, contract["artifact"], review, [], checks=checks
        )

    if review["hard_failures"]:
        return _blocked_cycle(
            cycle, review["hard_failures"], contract["artifact"], review, [], checks=checks
        )

    failed = list(validation["quality_feedback"])
    below_coverage = review["coverage"] < contract["coverage_gate"]
    if below_coverage:
        gaps = set(review.get("coverage_gaps", []))
        matching = [
            item
            for item in review["feedback"]
            if item.get("kind", "required_fix") == "required_fix" and item["criterion"] in gaps
        ]
        if not matching:
            return _blocked_cycle(
                cycle,
                ["coverage below gate without required_fix for a declared gap"],
                contract["artifact"],
                review,
                failed,
                checks=checks,
            )

    provided = {
        item["criterion"]
        for item in review["feedback"]
        if item.get("kind", "required_fix") == "required_fix"
    }
    if not set(failed) <= provided:
        return _blocked_cycle(
            cycle,
            ["required_fix missing for failed criterion"],
            contract["artifact"],
            review,
            failed,
            checks=checks,
        )

    actionable = [
        item for item in review["feedback"] if item.get("kind", "required_fix") == "required_fix"
    ]
    if review["decision"] == "feedback" and not actionable:
        return _blocked_cycle(
            cycle,
            ["feedback decision has no required_fix"],
            contract["artifact"],
            review,
            failed,
            checks=checks,
        )

    pending = bool(failed) or below_coverage or review["decision"] == "feedback"
    if pending:
        if cycle >= contract["max_cycles"]:
            return _blocked_cycle(
                cycle, ["quality gates not met"], contract["artifact"], review, failed, checks=checks
            )
        return {
            "status": "retry",
            "cycle_count": cycle,
            "feedback": deepcopy(review["feedback"]),
            "failed_criteria": sorted(failed),
            "advisory": validation["advisory"],
            "last_review": deepcopy(review),
            "checks": checks,
        }

    try:
        fingerprint = "sha256:" + sha256((root / contract["artifact"]).read_bytes()).hexdigest()
    except OSError as error:
        return _blocked_cycle(
            cycle,
            [f"artifact fingerprint failed: {error}"],
            contract["artifact"],
            review,
            failed,
            checks=checks,
        )
    return {
        "status": "approved",
        "cycle_count": cycle,
        "last_artifact": contract["artifact"],
        "artifact_fingerprint": fingerprint,
        "human_signoff": "pending",
        "advisory": validation["advisory"],
        "last_review": deepcopy(review),
        "checks": checks,
    }
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_gates.py -q`
Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add gauntlet_core.py tests/test_gates.py
git commit -m "feat: gates e avaliacao de ciclo"
```

---

### Task 5: Persistência idempotente do diário

**Files:**
- Modify: `gauntlet_core.py` (adiciona `_atomic_write`, `_load_json`, `_journal_dir`, `record_cycle`)
- Create: `tests/test_persistence.py`

**Interfaces:**
- Consumes: `evaluate_cycle`.
- Produces: `record_cycle(review, *, contract, cycle, workspace_root=None) -> dict` com o mesmo retorno de `evaluate_cycle`, após persistir `cycle-NN.json`, `events.json` e, em terminal, `state.json`.

- [ ] **Step 1: Escrever os testes**

`tests/test_persistence.py`:

```python
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
    directory = root / "runs" / "teste"
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
    first = (root / "runs" / "teste" / "cycle-01.json").read_text()
    record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)
    assert (root / "runs" / "teste" / "cycle-01.json").read_text() == first


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
    directory = root / "runs" / "teste"
    directory.mkdir(parents=True)
    (directory / "state.json").symlink_to(root / "out" / "artefato.md")
    with pytest.raises(ValueError):
        record_cycle(review(), contract=contract(), cycle=1, workspace_root=root)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_persistence.py -q`
Expected: FAIL com `ImportError: cannot import name 'record_cycle'`

- [ ] **Step 3: Implementar**

Adicionar import:

```python
import tempfile
```

Adicionar as funções:

```python
def _atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
    )
    try:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


def _load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"journal file is not valid JSON: {path}") from error


def _journal_dir(contract, root):
    if not contract["persistence_dir"]:
        return None
    return (root / contract["persistence_dir"]).resolve()


def record_cycle(review, *, contract, cycle, workspace_root=None):
    root = Path.cwd().resolve() if workspace_root is None else Path(workspace_root).resolve()
    validated = validate_contract(contract)
    if not validated["valid"]:
        raise ValueError("contract is invalid: " + "; ".join(validated["errors"]))
    contract = validated["contract"]
    result = evaluate_cycle(review, contract=contract, cycle=cycle, workspace_root=root)

    directory = _journal_dir(contract, root)
    if directory is None:
        return result

    payload = {
        "idempotency_key": [contract["run_id"], contract["artifact"], cycle],
        "review": deepcopy(review),
    }
    path = directory / f"cycle-{cycle:02d}.json"

    if path.exists():
        existing = _load_json(path, None)
        if (
            isinstance(existing, dict)
            and existing.get("idempotency_key") == payload["idempotency_key"]
            and existing.get("review") == payload["review"]
        ):
            return _load_json(directory / "state.json", None) or result
        raise ValueError("cycle already recorded with different content")

    if directory.exists():
        if not directory.is_dir() or any(item.is_symlink() for item in directory.iterdir()):
            raise ValueError("invalid journal directory")
        if (directory / "state.json").exists():
            raise ValueError("journal already terminal")

    cycles = sorted(directory.glob("cycle-*.json")) if directory.exists() else []
    events = _load_json(directory / "events.json", [])
    if len(cycles) != cycle - 1 or len(events) != 3 * (cycle - 1):
        raise ValueError("journal history is incomplete")

    _atomic_write(path, payload)
    events.extend(
        [
            {"cycle": cycle, "event": "cycle-start", "artifact": contract["artifact"]},
            {
                "cycle": cycle,
                "event": "deterministic-checks",
                "results": deepcopy(result.get("checks", [])),
            },
            {"cycle": cycle, "event": "review", "review": deepcopy(review)},
        ]
    )
    _atomic_write(directory / "events.json", events)
    if result["status"] != "retry":
        _atomic_write(directory / "state.json", result)
    return result
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_persistence.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add gauntlet_core.py tests/test_persistence.py
git commit -m "feat: diario idempotente do gauntlet-core"
```

---

### Task 6: Driver de ciclos e retomada

**Files:**
- Modify: `gauntlet_core.py` (adiciona `_resume` e `run_gauntlet`)
- Create: `tests/test_driver.py`

**Interfaces:**
- Consumes: `record_cycle`, `_journal_dir`, `_load_json`, `_blocked_cycle` (não), `evaluate_cycle`.
- Produces: `run_gauntlet(executor, reviewer, contract, workspace_root=None) -> dict`. `executor(feedback: list) -> None`; `reviewer(artifact: str, feedback: list) -> dict`.

- [ ] **Step 1: Escrever os testes**

`tests/test_driver.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest tests/test_driver.py -q`
Expected: FAIL com `ImportError: cannot import name 'run_gauntlet'`

- [ ] **Step 3: Implementar**

```python
def _resume(directory, contract, root):
    if not directory.exists():
        return 1, []
    if not directory.is_dir() or any(item.is_symlink() for item in directory.iterdir()):
        raise ValueError("invalid journal directory")
    files = sorted(directory.glob("cycle-*.json"))
    events = _load_json(directory / "events.json", [])
    if len(events) != 3 * len(files):
        raise ValueError("journal events are incomplete")
    feedback = []
    for index, path in enumerate(files, start=1):
        payload = _load_json(path, None)
        expected = [contract["run_id"], contract["artifact"], index]
        if not isinstance(payload, dict) or payload.get("idempotency_key") != expected:
            raise ValueError("journal cycle does not match the contract")
        result = evaluate_cycle(
            payload.get("review"), contract=contract, cycle=index, workspace_root=root
        )
        if result["status"] != "retry":
            raise ValueError("journal contains a terminal cycle")
        feedback = deepcopy(result["feedback"])
    return len(files) + 1, feedback


def run_gauntlet(executor, reviewer, contract, workspace_root=None):
    validated = validate_contract(contract)
    if not validated["valid"]:
        raise ValueError("contract is invalid: " + "; ".join(validated["errors"]))
    contract = validated["contract"]
    root = Path.cwd().resolve() if workspace_root is None else Path(workspace_root).resolve()
    directory = _journal_dir(contract, root)

    if directory is not None and (directory / "state.json").exists():
        return _load_json(directory / "state.json", None)

    next_cycle, feedback = (1, []) if directory is None else _resume(directory, contract, root)

    while next_cycle <= contract["max_cycles"]:
        executor(deepcopy(feedback))
        review = reviewer(contract["artifact"], deepcopy(feedback))
        result = record_cycle(review, contract=contract, cycle=next_cycle, workspace_root=root)
        if result["status"] != "retry":
            return result
        feedback = deepcopy(result["feedback"])
        next_cycle += 1

    raise ValueError("gauntlet exhausted without terminal result")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest tests/test_driver.py -q`
Expected: `6 passed`

- [ ] **Step 5: Rodar a suíte inteira**

Run: `pytest -q`
Expected: `67 passed`

- [ ] **Step 6: Commit**

```bash
git add gauntlet_core.py tests/test_driver.py
git commit -m "feat: driver de ciclos e retomada do gauntlet-core"
```

---

### Task 7: Contractos de exemplo e SKILL.md

**Files:**
- Create: `contracts/contrato-editorial.json`
- Create: `contracts/contrato-codigo.json`
- Create: `SKILL.md`

**Interfaces:**
- Produces: dois contratos válidos (`load_contract` aceita ambos) e a spec que o agente carrega.

- [ ] **Step 1: Criar os contratos**

`contracts/contrato-editorial.json`:

```json
{
  "name": "correcao-post-editorial",
  "goal": "Reescrever o draft corrigindo as falhas apontadas, preservando a voz do autor.",
  "artifact": "content/drafts/post.md",
  "criteria": [
    {"name": "clareza", "description": "Cada paragrafo tem uma ideia principal identificavel na primeira leitura.", "gate": 9},
    {"name": "voz_do_autor", "description": "Comparado ao guia de estilo do projeto, nao soa como texto generico de IA.", "gate": 9},
    {"name": "rastreabilidade", "description": "Toda afirmacao factual aponta para uma fonte declarada.", "gate": 10},
    {"name": "ritmo", "description": "Cadencia e variacao de frases; diagnostico, nao bloqueia.", "gate": 7, "blocking": false}
  ],
  "coverage_gate": 0.99,
  "max_cycles": 5,
  "checks": [
    {"name": "sem-placeholder", "run": "! grep -n 'TODO\\|TBD' content/drafts/post.md", "timeout_s": 15}
  ],
  "persistence_dir": "runs/correcao-post",
  "run_id": "correcao-post-01"
}
```

`contracts/contrato-codigo.json`:

```json
{
  "name": "feature-com-testes",
  "goal": "Implementar a feature pedida sem quebrar a suite existente.",
  "artifact": "src/feature.py",
  "criteria": [
    {"name": "testes_passam", "description": "A suite inteira passa; nenhum teste novo falha.", "gate": 10},
    {"name": "cobertura_do_caso", "description": "Cada requisito do pedido tem teste correspondente.", "gate": 9},
    {"name": "api_estavel", "description": "Nenhuma assinatura publica existente foi quebrada.", "gate": 9},
    {"name": "legibilidade", "description": "Nomes e fluxo compreensiveis sem comentario explicativo.", "gate": 8}
  ],
  "max_cycles": 5,
  "checks": [
    {"name": "pytest", "run": "pytest -q", "timeout_s": 300},
    {"name": "sem-debug", "run": "! grep -rn 'breakpoint()\\|pdb.set_trace' src", "timeout_s": 15}
  ],
  "persistence_dir": "runs/feature",
  "run_id": "feature-01"
}
```

- [ ] **Step 2: Testar que os dois contratos carregam**

Criar `tests/test_contracts_examples.py`:

```python
from pathlib import Path

from gauntlet_core import load_contract

ROOT = Path(__file__).resolve().parent.parent


def test_examples_load():
    for name in ("contrato-editorial.json", "contrato-codigo.json"):
        contract = load_contract(ROOT / "contracts" / name)
        assert contract["criteria"]
        assert any(criterion["blocking"] for criterion in contract["criteria"])
```

Run: `pytest tests/test_contracts_examples.py -q`
Expected: `1 passed`

- [ ] **Step 3: Escrever o SKILL.md**

`SKILL.md`:

```markdown
---
name: gauntlet-core
description: |
  Executa uma tarefa em ciclos isolados de executor e revisor, com checks deterministicos,
  gates numericos e bloqueio fail-closed. Os criterios de qualidade vem de um contrato JSON
  da propria tarefa.

  Acionada quando o usuario menciona:
  - "roda o gauntlet"
  - "gauntlet com contrato"
  - "loop de qualidade ate passar"
  - "executor e revisor em ciclos"
  - "quero um gate de qualidade para esta tarefa"
---

# Gauntlet Core

Você não julga a qualidade por conta própria. Você captura os critérios da tarefa num contrato,
executa o ciclo e deixa o motor decidir `approved` ou `blocked`.

## Quando usar

- Existe um artefato verificável (arquivo, página, código, documento) e um padrão de qualidade
  que pode ser descrito em critérios numéricos.
- O trabalho pode ser refeito em ciclos com feedback acionável.
- Alguém vai revisar no final e precisa de rastro de por que aquilo passou.

## Quando NÃO usar

- A tarefa não tem critério de qualidade declarado: a resposta é "não dá para rodar o gauntlet",
  não um critério inventado.
- O artefato não é verificável (uma conversa, uma decisão, um e-mail enviado).
- A aprovação final é humana e irrevogável e ninguém quer ciclo automático antes.

## Camada 1 — Capturar os critérios no contrato

Pergunte, uma por vez, e registre a resposta literal:

1. Qual arquivo é o artefato e onde ele fica (caminho relativo ao workspace)?
2. O que reprova sem discussão? (vira critério bloqueante com `gate` 9 ou 10)
3. O que é "bom" mas não impede entrega? (vira `blocking: false`)
4. Qual o piso numérico de cada critério, de 0 a 10?
5. Existe comando que precisa passar antes do revisor? (testes, build, lint, grep)
6. Quantos ciclos no máximo, de 1 a 5?

Regra dura: nunca invente critério que a tarefa não declarou. Se faltar resposta, pare e pergunte.

Escreva o contrato em JSON e valide com `load_contract`. Exemplo mínimo:

{
  "name": "correcao-post",
  "goal": "Reescrever o draft corrigindo as falhas apontadas.",
  "artifact": "content/drafts/post.md",
  "criteria": [
    {"name": "clareza", "description": "Cada paragrafo tem uma ideia principal.", "gate": 9}
  ],
  "max_cycles": 5,
  "persistence_dir": "runs/correcao-post",
  "run_id": "correcao-post-01"
}

Erros comuns: critério vago ("qualidade"), gate frouxo para compensar revisor ruim, artefato
absoluto, feedback sem `fix`, contrato sem nenhum critério bloqueante.

## Camada 2 — Executar o ciclo

Com Python disponível, use o motor:

    from gauntlet_core import load_contract, run_gauntlet

    contrato = load_contract("caminho/contrato.json")
    resultado = run_gauntlet(executor, revisor, contrato, workspace_root=".")

    def executor(feedback):
        # task nova e isolada; escreve o artefato no caminho do contrato
        ...

    def revisor(artifact, feedback):
        # task nova e isolada, diferente do executor; devolve o review JSON
        ...

Sem Python, conduza os ciclos manualmente com as mesmas regras e marque o resultado com
`"verified_by": "agent"` em vez de `"motor"`.

Protocolo obrigatório em cada ciclo:

1. Registre o início do ciclo e o número.
2. Chame o executor numa `task` nova, com contexto novo e apenas o `feedback` do ciclo anterior.
3. Rode os checks determinísticos antes de chamar o revisor. Falha de check bloqueia na hora.
4. Chame o revisor em outra `task` nova, diferente do executor, entregando artefato, contrato e
   feedback. Ele devolve JSON com `decision`, `coverage`, `criteria`, `hard_failures`, `feedback`,
   `artifact` e, quando houver lacuna de cobertura, `coverage_gaps`.
5. Aceite só JSON válido e completo. Texto livre, JSON truncado ou aprovação verbal não contam.
6. Se o gate reprovar com feedback completo, inicie o próximo ciclo com esse feedback.
7. Pare em `approved` ou `blocked`. Nunca abra sexto ciclo.

## Encerramento

- `approved` sempre traz `"human_signoff": "pending"`. Entregue o artefato e diga:
  "pronto para seu QA". Nunca declare a tarefa aprovada.
- `blocked` entrega `failure_reasons`, `failed_criteria`, `last_review` e `feedback`.
  Não mascare, não "quase aprove", não continue a fila por conta própria.

## Anti-padrões

- Revisor igual ao executor, ou com o mesmo contexto.
- Feedback genérico ("melhorar") sem `criterion` e `fix`.
- Aprovar porque o ciclo acabou.
- Reexecutar um `run_id` já aprovado; revisão de trabalho aprovado exige `run_id` novo.
- Escrever artefato fora do caminho declarado.
```

- [ ] **Step 4: Rodar a suíte**

Run: `pytest -q`
Expected: `68 passed`

- [ ] **Step 5: Commit**

```bash
git add SKILL.md contracts tests/test_contracts_examples.py
git commit -m "feat: skill e contratos de exemplo"
```

---

### Task 8: Cópias por harness, README e licença

**Files:**
- Create: `scripts/build-harness-copies.sh`
- Create: `tests/test_harness_copies.py`
- Create: `README.md`
- Create: `LICENSE`
- Create: `examples/diario-exemplo/cycle-01.json`
- Create: `examples/diario-exemplo/events.json`
- Create: `examples/diario-exemplo/state.json`

**Interfaces:**
- Produces: `agents/skills/gauntlet-core/`, `.claude/skills/gauntlet-core/`, `opencode/skills/gauntlet-core/`, cada um com `SKILL.md`, `gauntlet_core.py`, `contracts/` e `examples/`.

- [ ] **Step 1: Escrever o script de geração**

`scripts/build-harness-copies.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
name="gauntlet-core"

for target in "agents/skills" ".claude/skills" "opencode/skills"; do
  dest="$root/$target/$name"
  mkdir -p "$dest"
  cp "$root/SKILL.md" "$dest/SKILL.md"
  cp "$root/gauntlet_core.py" "$dest/gauntlet_core.py"
  rm -rf "$dest/contracts" "$dest/examples"
  cp -R "$root/contracts" "$dest/contracts"
  cp -R "$root/examples" "$dest/examples"
done

echo "copias geradas para $name"
```

Run: `chmod +x scripts/build-harness-copies.sh && bash scripts/build-harness-copies.sh`
Expected: `copias geradas para gauntlet-core`

- [ ] **Step 2: Escrever o teste anti-drift**

`tests/test_harness_copies.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("agents/skills", ".claude/skills", "opencode/skills")
FILES = (
    "SKILL.md",
    "gauntlet_core.py",
    "contracts/contrato-editorial.json",
    "contracts/contrato-codigo.json",
)


def test_harness_copies_match_canonical():
    for target in TARGETS:
        for relative in FILES:
            canonical = (ROOT / relative).read_bytes()
            copy = (ROOT / target / "gauntlet-core" / relative).read_bytes()
            assert copy == canonical, f"{target}/gauntlet-core/{relative} divergiu do canonico"
```

Run: `pytest tests/test_harness_copies.py -q`
Expected: `1 passed`

- [ ] **Step 3: Criar o diário de exemplo**

`examples/diario-exemplo/cycle-01.json`:

```json
{
  "idempotency_key": ["exemplo", "out/artefato.md", 1],
  "review": {
    "decision": "approved",
    "coverage": 1.0,
    "criteria": {"clareza": 9},
    "hard_failures": [],
    "feedback": [],
    "artifact": "out/artefato.md"
  }
}
```

`examples/diario-exemplo/events.json`:

```json
[
  {"cycle": 1, "event": "cycle-start", "artifact": "out/artefato.md"},
  {"cycle": 1, "event": "deterministic-checks", "results": []},
  {"cycle": 1, "event": "review", "review": {"decision": "approved", "coverage": 1.0, "criteria": {"clareza": 9}, "hard_failures": [], "feedback": [], "artifact": "out/artefato.md"}}
]
```

`examples/diario-exemplo/state.json`:

```json
{
  "status": "approved",
  "cycle_count": 1,
  "last_artifact": "out/artefato.md",
  "artifact_fingerprint": "sha256:exemplo",
  "human_signoff": "pending",
  "advisory": [],
  "checks": []
}
```

- [ ] **Step 4: Escrever o README**

`README.md`:

```markdown
# Gauntlet Core

Motor genérico de ciclos executor → checks → revisor → gate. Os critérios de qualidade vêm de um
contrato JSON da própria tarefa, então o mesmo motor serve para texto, código, documento ou deck.

Diferente da skill pública `gauntlet-loop`, que só escreve um prompt, esta executa o ciclo com
gates determinísticos, diário idempotente e veredito `approved`/`blocked`.

## Como funciona

1. A tarefa declara seus critérios num contrato JSON (`gate` 1–10 por critério, `blocking`
   opcional, `checks` opcionais).
2. O executor escreve o artefato numa chamada isolada.
3. O motor roda os checks determinísticos.
4. Um revisor diferente, com contexto novo, devolve JSON estruturado.
5. O gate aprova, pede novo ciclo com feedback, ou bloqueia. No máximo 5 ciclos.
6. `approved` sai com `human_signoff: "pending"`: o QA humano continua sendo seu.

## Instalação

### Via `npx skills`

    npx skills add <owner>/skill-gauntlet-core@gauntlet-core -g -y

Troque `<owner>` pelo dono do repositório. Sem `-g`, instala no projeto atual.

### Manual, global

| Harness | Destino |
|---|---|
| agents | `~/.agents/skills/gauntlet-core` |
| Claude Code | `~/.claude/skills/gauntlet-core` |
| Codex | `~/.codex/skills/gauntlet-core` |
| OpenCode | `~/.config/opencode/skills/gauntlet-core` |
| Hermes | `~/.hermes/skills/gauntlet-core` |
| OpenClaw | `~/.openclaw/skills/gauntlet-core` |

### Manual, por projeto

| Harness | Destino |
|---|---|
| agents | `<projeto>/.agents/skills/gauntlet-core` |
| Claude Code | `<projeto>/.claude/skills/gauntlet-core` |
| Codex | `<projeto>/.codex/skills/gauntlet-core` |
| OpenCode | `<projeto>/.opencode/skills/gauntlet-core` |
| Hermes | `<projeto>/.hermes/skills/gauntlet-core` |
| OpenClaw | `<projeto>/.openclaw/skills/gauntlet-core` |

Copie o diretório inteiro: `SKILL.md`, `gauntlet_core.py`, `contracts/` e `examples/`. Cópia por
symlink não funciona com `npx skills add`.

Para Claude Code a partir de `~/.agents`, a skill `migrate-agent-skills` sincroniza via symlink:

    migrate-skills sync-to-claude --source agents

## Uso

    from gauntlet_core import load_contract, run_gauntlet
    contrato = load_contract("contracts/contrato-codigo.json")
    resultado = run_gauntlet(executor, revisor, contrato, workspace_root=".")

Ou conduza ciclo a ciclo com `record_cycle`, quando o agente faz as chamadas `task`.

## Desenvolvimento

    pytest -q
    bash scripts/build-harness-copies.sh
    pytest tests/test_harness_copies.py -q

As cópias em `agents/`, `.claude/` e `opencode/` são geradas; teste garante que não divergem.

## Licença

MIT.
```

- [ ] **Step 5: Escrever a licença**

`LICENSE`:

```text
MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 6: Regerar cópias e rodar tudo**

Run: `bash scripts/build-harness-copies.sh && pytest -q`
Expected: `69 passed`

- [ ] **Step 7: Commit**

```bash
git add scripts tests/test_harness_copies.py README.md LICENSE examples
git add agents .claude opencode
git commit -m "feat: empacotamento multi-harness e documentacao"
```

---

### Task 9: Instalação global e smoke end-to-end

**Files:**
- Modify: nenhum
- Create: `/Users/mac/.agents/skills/gauntlet-core/` (cópia instalada)

**Interfaces:**
- Consumes: `agents/skills/gauntlet-core`.
- Produces: skill visível globalmente.

- [ ] **Step 1: Instalar globalmente**

```bash
mkdir -p ~/.agents/skills
rm -rf ~/.agents/skills/gauntlet-core
cp -R "/Users/mac/llm server/projetos/skill-gauntlet-core/agents/skills/gauntlet-core" ~/.agents/skills/gauntlet-core
ls ~/.agents/skills/gauntlet-core
```

Expected: `SKILL.md`, `gauntlet_core.py`, `contracts`, `examples`

- [ ] **Step 2: Smoke de 1 ciclo com artefato real**

```bash
tmp="$(mktemp -d)"
mkdir -p "$tmp/out"
printf 'conteudo revisado\n' > "$tmp/out/artefato.md"
cd "/Users/mac/llm server/projetos/skill-gauntlet-core"
python3 - "$tmp" <<'PY'
import json, sys
from pathlib import Path
from gauntlet_core import run_gauntlet, validate_contract

root = Path(sys.argv[1])
contract = validate_contract({
    "name": "smoke",
    "goal": "smoke test",
    "artifact": "out/artefato.md",
    "criteria": [{"name": "clareza", "description": "legivel", "gate": 9}],
    "persistence_dir": "runs/smoke",
    "run_id": "smoke-01",
})["contract"]

result = run_gauntlet(lambda feedback: None,
                      lambda artifact, feedback: {
                          "decision": "approved", "coverage": 1.0,
                          "criteria": {"clareza": 9}, "hard_failures": [],
                          "feedback": [], "artifact": "out/artefato.md"},
                      contract, workspace_root=root)
print(json.dumps({"status": result["status"], "signoff": result["human_signoff"]}))
assert result["status"] == "approved"
assert result["human_signoff"] == "pending"
assert (root / "runs" / "smoke" / "state.json").exists()
PY
rm -rf "$tmp"
```

Expected: `{"status": "approved", "signoff": "pending"}`

- [ ] **Step 3: Verificar que a skill aparece na próxima sessão**

Reinicie a sessão do agente (ou abra uma nova) e confirme que `gauntlet-core` aparece na lista de skills disponíveis. Se o harness usar `~/.claude/skills`, sincronize com `migrate-skills sync-to-claude --source agents`.

- [ ] **Step 4: Commit final do estado do repo**

```bash
git add -A
git status --short
git commit -m "chore: versao instalavel do gauntlet-core" --allow-empty
```

---

### Task 10: Publicação no GitHub

**Files:**
- Modify: nenhum
- Create: repositório remoto `skill-gauntlet-core`

**Gate obrigatório:** só executar depois que o usuário responder **público ou privado**. A skill
`github-skill-publisher` proíbe criar repositório sem essa confirmação explícita.

- [ ] **Step 1: Perguntar visibilidade ao usuário**

Pergunta exata: "O repositório `skill-gauntlet-core` deve ser público ou privado?"

- [ ] **Step 2: Criar o repositório e publicar**

```bash
gh repo create skill-gauntlet-core --<public|private> --source . --remote origin --push
```

Expected: URL do repositório e push concluído.

- [ ] **Step 3: Verificar a instalação via npx num diretório temporário**

```bash
tmp="$(mktemp -d)"
cd "$tmp"
npx -y skills add github:<owner>/skill-gauntlet-core@gauntlet-core -g -y
ls ~/.agents/skills/gauntlet-core
rm -rf "$tmp"
```

Expected: `SKILL.md`, `gauntlet_core.py`, `contracts`, `examples`

- [ ] **Step 4: Reportar**

Informar URL, comando `npx` validado e o aviso de que `human_signoff` continua obrigatório.

---

## Self-Review

**Cobertura da spec:**

| Requisito | Task |
|---|---|
| Contrato JSON + validação estrita | 1 |
| Review estrito + `coverage_gaps` + `blocking: false` | 2 |
| Checks estruturais + comandos opcionais | 3 |
| Gates na ordem + `approved`/`retry`/`blocked` + `human_signoff` | 4 |
| Diário atômico, idempotente, terminal único | 5 |
| Driver, retomada, proibição de 6º ciclo | 6 |
| Contratos de exemplo + SKILL.md em duas camadas | 7 |
| Cópias multi-harness + anti-drift + README + MIT | 8 |
| Instalação global + smoke | 9 |
| Publicação com confirmação de visibilidade | 10 |

**Sem placeholders:** todo passo com código tem o código completo; comandos têm saída esperada.

**Consistência de tipos:** `validate_contract` retorna `contract` normalizado; `evaluate_cycle` e
`record_cycle` recebem contrato normalizado e revalidam; `run_checks` devolve
`{"name","status","exit_code","output"}` usado em `events.json`; `_resume` usa
`idempotency_key == [run_id, artifact, cycle]`, igual a `record_cycle`.
