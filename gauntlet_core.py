"""Motor generico do Gauntlet: contrato de qualidade -> ciclos -> approved/blocked."""

import json
import math
import os
import signal
import subprocess
import tempfile
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
        if path.drive or path.root:
            return "must not be drive-relative or rooted"
    return None


def _run_id_error(value):
    if not isinstance(value, str) or not value.strip():
        return "must be a non-empty string"
    if value in (".", ".."):
        return "must not be a reserved path component"
    if "/" in value or "\\" in value:
        return "must be a single path component"
    win = PureWindowsPath(value)
    if win.drive or win.root:
        return "must be a single path component"
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
        elif item_name != item_name.strip():
            errors.append(f"{prefix}.name must not have surrounding whitespace")
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
    run_id_error = _run_id_error(run_id)
    if run_id_error:
        errors.append(f"run_id {run_id_error}")

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


def _kill_group(process):
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except OSError:
        try:
            process.kill()
        except OSError:
            pass


def run_checks(contract, workspace_root=None):
    root = Path.cwd().resolve() if workspace_root is None else Path(workspace_root).resolve()
    results = []
    for check in contract["checks"]:
        try:
            process = subprocess.Popen(
                check["run"],
                shell=True,
                cwd=str(root),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            results.append(
                {"name": check["name"], "status": "error", "exit_code": None, "output": str(error)}
            )
            continue
        try:
            process.wait(timeout=check["timeout_s"])
        except subprocess.TimeoutExpired:
            _kill_group(process)
            try:
                stdout, stderr = process.communicate()
            except OSError:
                stdout, stderr = "", ""
            partial = ((stdout or "") + (stderr or "")).strip()[:2000]
            output = f"timeout after {check['timeout_s']}s"
            if partial:
                output += f": {partial}"
            results.append(
                {"name": check["name"], "status": "error", "exit_code": None, "output": output}
            )
            continue
        stdout, stderr = process.communicate()
        output = (stdout or "") + (stderr or "")
        results.append(
            {
                "name": check["name"],
                "status": "pass" if process.returncode == 0 else "fail",
                "exit_code": process.returncode,
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


def evaluate_cycle(review, *, contract, cycle, workspace_root=None, checks=None):
    root = Path.cwd().resolve() if workspace_root is None else Path(workspace_root).resolve()
    if not _is_int(cycle) or not 1 <= cycle <= contract["max_cycles"]:
        raise ValueError("cycle must be an integer within max_cycles")

    validation = validate_review(review, contract)
    if not validation["valid"]:
        return _blocked_cycle(cycle, validation["errors"], contract["artifact"], review, [])

    if review["hard_failures"]:
        return _blocked_cycle(cycle, review["hard_failures"], contract["artifact"], review, [])

    artifact_errors = _artifact_errors(root, contract["artifact"])
    if artifact_errors:
        return _blocked_cycle(cycle, artifact_errors, contract["artifact"], review, [])

    if checks is None:
        checks = run_checks(contract, root)
    failed_checks = [
        f"check failed: {item['name']}" for item in checks if item["status"] != "pass"
    ]
    if failed_checks:
        return _blocked_cycle(
            cycle, failed_checks, contract["artifact"], review, [], checks=checks
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


def _atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False
    )
    tmp_name = handle.name
    try:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    except BaseException:
        handle.close()
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    else:
        handle.close()
    os.replace(tmp_name, path)


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
    root = Path(root).resolve()
    parts = list(Path(contract["persistence_dir"]).parts) + [contract["run_id"]]
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("journal directory must not contain symlinks")
    journal = current.resolve()
    try:
        journal.relative_to(root)
    except ValueError:
        raise ValueError("journal directory escapes the workspace")
    return journal


def _validate_state(state, contract):
    if not isinstance(state, dict):
        raise ValueError("journal state must be an object")
    if state.get("status") not in ("approved", "blocked"):
        raise ValueError("journal state has an invalid status")
    cycle_count = state.get("cycle_count")
    if not _is_int(cycle_count) or not 1 <= cycle_count <= contract["max_cycles"]:
        raise ValueError("journal state has an invalid cycle_count")
    if state.get("last_artifact") != contract["artifact"]:
        raise ValueError("journal state artifact does not match the contract")
    if state.get("status") == "approved" and state.get("human_signoff") != "pending":
        raise ValueError("approved journal state must be pending human signoff")


def _check_cycle_events(events, cycle):
    start = 3 * (cycle - 1)
    names = [
        entry.get("event") if isinstance(entry, dict) else None
        for entry in events[start : start + 3]
    ]
    if names != ["cycle-start", "deterministic-checks", "review"]:
        raise ValueError("journal events are incomplete")
    for entry in events[start : start + 3]:
        if entry.get("cycle") != cycle:
            raise ValueError("journal events are incomplete")


def _check_preflight_events(events, cycle):
    start = 3 * (cycle - 1)
    names = [
        entry.get("event") if isinstance(entry, dict) else None
        for entry in events[start : start + 2]
    ]
    if names != ["cycle-start", "deterministic-checks"]:
        raise ValueError("journal events are incomplete")
    for entry in events[start : start + 2]:
        if entry.get("cycle") != cycle:
            raise ValueError("journal events are incomplete")


def _validate_journal(directory, contract):
    """Valida o diário e devolve (cycles, events, state).

    `cycles` é a lista de payloads dos arquivos `cycle-NN.json` em ordem (índice = posição + 1);
    `events` é a lista de eventos; `state` é o estado terminal validado, ou `None`.
    """
    if directory is None:
        return [], [], None
    if not directory.exists():
        return [], [], None
    if not directory.is_dir():
        raise ValueError("journal path is not a directory")
    if any(entry.is_symlink() for entry in directory.iterdir()):
        raise ValueError("journal directory must not contain symlinks")

    files = sorted(directory.glob("cycle-*.json"))
    expected = [f"cycle-{index:02d}.json" for index in range(1, len(files) + 1)]
    if [path.name for path in files] != expected:
        raise ValueError("journal cycle files are out of sequence")

    events = _load_json(directory / "events.json", None)
    if events is None:
        events = []
    if not isinstance(events, list):
        raise ValueError("journal events are not a list")

    state = None
    state_path = directory / "state.json"
    if state_path.exists():
        if state_path.is_symlink() or not state_path.is_file():
            raise ValueError("journal state must be a regular file")
        state = _load_json(state_path, None)
        _validate_state(state, contract)

    n = len(files)
    total = len(events)
    preflight = False
    if total == 3 * n:
        pass
    elif total == 3 * n + 2:
        preflight = True
    else:
        raise ValueError("journal events are incomplete")

    cycles = []
    for index, path in enumerate(files, start=1):
        payload = _load_json(path, None)
        expected_key = [contract["run_id"], contract["artifact"], index]
        if not isinstance(payload, dict) or payload.get("idempotency_key") != expected_key:
            raise ValueError("journal cycle does not match the contract")
        _check_cycle_events(events, index)
        review = payload.get("review")
        if not validate_review(review, contract)["valid"]:
            raise ValueError("journal contains an invalid review")
        cycles.append(payload)

    if preflight:
        _check_preflight_events(events, n + 1)
        if state is None or state.get("status") != "blocked":
            raise ValueError("preflight journal must be blocked")
    return cycles, events, state


def _stored_checks(events, index):
    start = 3 * (index - 1)
    entry = events[start + 1]
    results = entry.get("results") if isinstance(entry, dict) else None
    return results if isinstance(results, list) else []


def _persistence_blocked(cycle, contract, review, error, checks=None):
    return _blocked_cycle(
        cycle, [f"persistence failed: {error}"], contract["artifact"], review, [], checks=checks
    )


def record_cycle(review, *, contract, cycle, workspace_root=None, checks=None):
    root = Path.cwd().resolve() if workspace_root is None else Path(workspace_root).resolve()
    validated = validate_contract(contract)
    if not validated["valid"]:
        raise ValueError("contract is invalid: " + "; ".join(validated["errors"]))
    contract = validated["contract"]
    if not _is_int(cycle) or not 1 <= cycle <= contract["max_cycles"]:
        raise ValueError("cycle must be an integer within max_cycles")

    try:
        directory = _journal_dir(contract, root)
    except OSError as error:
        return _persistence_blocked(cycle, contract, review, error, checks)

    if directory is None:
        return evaluate_cycle(review, contract=contract, cycle=cycle, workspace_root=root, checks=checks)

    payload = {
        "idempotency_key": [contract["run_id"], contract["artifact"], cycle],
        "review": deepcopy(review),
    }
    path = directory / f"cycle-{cycle:02d}.json"

    try:
        cycles, events, state = _validate_journal(directory, contract)

        if cycle <= len(cycles):
            existing = cycles[cycle - 1]
            if existing.get("review") != payload["review"]:
                raise ValueError("cycle already recorded with different content")
            if state is not None:
                return state
            return evaluate_cycle(review, contract=contract, cycle=cycle, workspace_root=root, checks=checks)

        if cycle != len(cycles) + 1:
            raise ValueError("journal history is incomplete")
        if state is not None:
            raise ValueError("journal already terminal")

        result = evaluate_cycle(review, contract=contract, cycle=cycle, workspace_root=root, checks=checks)
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
        _atomic_write(path, payload)
        _atomic_write(directory / "events.json", events)
        if result["status"] != "retry":
            _atomic_write(directory / "state.json", result)
    except (OSError, TypeError) as error:
        return _persistence_blocked(cycle, contract, review, error, checks)
    return result


def _persist_preflight(directory, contract, cycle, result):
    if directory is None:
        return result
    try:
        cycles, events, state = _validate_journal(directory, contract)
    except OSError as error:
        return _persistence_blocked(cycle, contract, {}, error, result.get("checks"))
    if state is not None:
        raise ValueError("journal already terminal")
    if cycle != len(cycles) + 1:
        raise ValueError("journal history is incomplete")
    events.extend(
        [
            {"cycle": cycle, "event": "cycle-start", "artifact": contract["artifact"]},
            {
                "cycle": cycle,
                "event": "deterministic-checks",
                "results": deepcopy(result.get("checks", [])),
            },
        ]
    )
    try:
        _atomic_write(directory / "events.json", events)
        _atomic_write(directory / "state.json", result)
    except (OSError, TypeError) as error:
        return _persistence_blocked(cycle, contract, {}, error, result.get("checks"))
    return result


def _resume(cycles, events, contract, root):
    feedback = []
    for index, payload in enumerate(cycles, start=1):
        checks = _stored_checks(events, index)
        result = evaluate_cycle(
            payload.get("review"),
            contract=contract,
            cycle=index,
            workspace_root=root,
            checks=checks,
        )
        if result["status"] != "retry":
            raise ValueError("journal does not reproduce the stored cycle outcome")
        feedback = deepcopy(result["feedback"])
    return len(cycles) + 1, feedback


def run_gauntlet(executor, reviewer, contract, workspace_root=None):
    """Executa os ciclos com o executor e o revisor fornecidos.

    Os checks deterministicos rodam aqui, antes de cada chamada ao revisor. No modo
    conduzido por agente (record_cycle), quem chama precisa rodar os checks antes de
    despachar o revisor.
    """
    validated = validate_contract(contract)
    if not validated["valid"]:
        raise ValueError("contract is invalid: " + "; ".join(validated["errors"]))
    contract = validated["contract"]
    root = Path.cwd().resolve() if workspace_root is None else Path(workspace_root).resolve()
    directory = _journal_dir(contract, root)

    if directory is None:
        cycles, events, state = [], [], None
    else:
        cycles, events, state = _validate_journal(directory, contract)

    if state is not None:
        return state

    next_cycle, feedback = _resume(cycles, events, contract, root)

    while next_cycle <= contract["max_cycles"]:
        executor(deepcopy(feedback))
        preflight_errors = _artifact_errors(root, contract["artifact"])
        checks = [] if preflight_errors else run_checks(contract, root)
        failed_checks = [
            f"check failed: {item['name']}" for item in checks if item["status"] != "pass"
        ]
        if preflight_errors or failed_checks:
            result = _blocked_cycle(
                next_cycle,
                preflight_errors or failed_checks,
                contract["artifact"],
                {},
                [],
                checks=checks,
            )
            return _persist_preflight(directory, contract, next_cycle, result)
        review = reviewer(contract["artifact"], deepcopy(feedback))
        result = record_cycle(review, contract=contract, cycle=next_cycle, workspace_root=root, checks=checks)
        if result["status"] != "retry":
            return result
        feedback = deepcopy(result["feedback"])
        next_cycle += 1

    raise ValueError("gauntlet exhausted without terminal result")
