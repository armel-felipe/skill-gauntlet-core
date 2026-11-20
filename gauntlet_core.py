"""Motor generico do Gauntlet: contrato de qualidade -> ciclos -> approved/blocked."""

import json
import math
from copy import deepcopy
from hashlib import sha256
from numbers import Real
from pathlib import Path, PurePosixPath, PureWindowsPath

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
    for flavour in (PurePosixPath, PureWindowsPath):
        path = flavour(value)
        if path.is_absolute():
            return "must be relative to the workspace"
        if ".." in path.parts:
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
