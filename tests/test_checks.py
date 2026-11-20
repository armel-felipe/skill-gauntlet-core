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
