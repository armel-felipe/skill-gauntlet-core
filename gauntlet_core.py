"""Motor generico do Gauntlet: contrato de qualidade -> ciclos -> approved/blocked."""

import json
import math
import subprocess
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
REVIEW_REQUIRED = {"decision", "coverage", "criteria", "hard_failures", "feedback", "artifact"}
REVIEW_OPTIONAL = {"coverage_gaps"}
FEEDBACK_KEYS = {"criterion", "kind", "fix"}
DECISIONS = {"approved", "feedback"}
KINDS = {"required_fix", "optional_suggestion"}


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
    if not isinstance(decision, str) or decision not in DECISIONS:
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
        criterion_name = item.get("criterion")
        if not isinstance(criterion_name, str) or criterion_name not in gates:
            errors.append(f"{prefix}.criterion must be one of the contract criteria")
        kind = item.get("kind", "required_fix")
        if not isinstance(kind, str) or kind not in KINDS:
            errors.append(f"{prefix}.kind must be required_fix or optional_suggestion")
        fix = item.get("fix")
        if not isinstance(fix, str) or not fix.strip():
            errors.append(f"{prefix}.fix must be a non-empty string")

    gaps = review.get("coverage_gaps", [])
    if not isinstance(gaps, list) or not all(
        isinstance(gap, str) and gap in gates for gap in gaps
    ):
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


def _artifact_errors(root, artifact):
    root = Path(root).resolve()
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


def _blocked_cycle(cycle, reasons, artifact, review, failed_criteria, checks=None):
    raw_feedback = review.get("feedback") if isinstance(review, dict) else None
    feedback = raw_feedback if isinstance(raw_feedback, list) else []
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
