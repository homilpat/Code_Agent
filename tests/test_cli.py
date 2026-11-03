import json
import sys
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from kh_agent.cli.app import app

runner = CliRunner()


def test_help_and_doctor_do_not_require_linux():
    assert runner.invoke(app, ["--help"]).exit_code == 0
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["sandbox"] == "REQUIRES_ROOTLESS_PODMAN_AND_PREBUILT_IMAGE"
    assert payload["approval_apply"] == "NOT_AVAILABLE"


@pytest.mark.skipif(sys.platform == "linux", reason="Windows production gate")
def test_windows_stateful_commands_fail_closed(tmp_path):
    result = runner.invoke(app, ["--store", str(tmp_path / "private"), "init"])
    assert result.exit_code == 2
    assert "UNSUPPORTED_PLATFORM" in result.output
    assert not (tmp_path / "private").exists()


def test_local_cli_registration_status_and_history(environment, monkeypatch, tmp_path):
    # Cross-platform CLI wiring test with explicit test-only runtime/DB injection.
    # This does not certify the Linux filesystem or sandbox implementation.
    env = environment
    monkeypatch.setattr("kh_agent.cli.app.require_linux_store", lambda root: root)
    monkeypatch.setattr("kh_agent.cli.app.Database", lambda path: env.db)
    monkeypatch.setattr(env.db, "close", lambda: None)
    result = runner.invoke(
        app, ["--store", str(tmp_path / "store"), "status", "--repo", str(env.repo)]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["repository_id"] == env.repository_id
    result = runner.invoke(app, ["history", "--repo", str(env.repo)])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["events"]
    # The fixture has refs but no commit objects: on Linux Safe Git resolves HEAD as UNRESOLVED
    # and blocks; elsewhere inspection is unsupported. Either way mutation fails closed.
    result = runner.invoke(app, ["modify", "change requested", "--repo", str(env.repo)])
    assert result.exit_code == 2
    expected = "REPOSITORY_STATE_BLOCKED" if sys.platform == "linux" else "UNSUPPORTED_PLATFORM"
    assert expected in result.output


def test_apply_has_no_auto_approve_switch():
    result = runner.invoke(app, ["apply", "--yes"])
    assert result.exit_code != 0


def test_modify_routes_targeted_request_to_local_preview(monkeypatch, tmp_path):
    seen = {}

    def preview(path, target, request, model, port):
        seen.update(path=path, target=target, request=request, model=model, port=port)
        return {"status": "MODEL_PREVIEW_ONLY"}

    monkeypatch.setattr("kh_agent.cli.app.require_linux_store", lambda root: root)
    monkeypatch.setattr(
        "kh_agent.cli.app.Database", lambda path: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(
        "kh_agent.cli.app._application",
        lambda ctx, db: SimpleNamespace(generate_preview=preview),
    )
    result = runner.invoke(
        app,
        [
            "--store",
            str(tmp_path),
            "modify",
            "Fix the value",
            "--target",
            "app.py",
            "--model",
            "local/model",
            "--port",
            "1234",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen["target"] == "app.py" and seen["model"] == "local/model"
    assert seen["request"] == "Fix the value" and seen["port"] == 1234


def test_semantic_cli_routes_location_and_image(monkeypatch, tmp_path):
    seen = {}

    def semantic_query(path, target, line, column, image):
        seen.update(path=path, target=target, line=line, column=column, image=image)
        return {"status": "SANDBOXED_SEMANTIC_PARTIAL"}

    monkeypatch.setattr("kh_agent.cli.app.require_linux_store", lambda root: root)
    monkeypatch.setattr(
        "kh_agent.cli.app.Database", lambda path: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(
        "kh_agent.cli.app._application",
        lambda ctx, db: SimpleNamespace(semantic_query=semantic_query),
    )
    result = runner.invoke(
        app,
        [
            "semantic",
            "src/app.py",
            "--line",
            "5",
            "--column",
            "10",
            "--image",
            "a" * 64,
            "--repo",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen == {
        "path": tmp_path,
        "target": "src/app.py",
        "line": 5,
        "column": 10,
        "image": "a" * 64,
    }


def test_modify_routes_generated_candidate_to_test_and_requires_both_options(monkeypatch, tmp_path):
    seen = {}

    def generate_and_verify(path, target, request, model, image, tests, port):
        seen.update(
            target=target, request=request, model=model, image=image, tests=tests, port=port
        )
        return {"status": "MODEL_TEST_EXPERIMENTAL", "apply_ready": False}

    monkeypatch.setattr("kh_agent.cli.app.require_linux_store", lambda root: root)
    monkeypatch.setattr(
        "kh_agent.cli.app.Database", lambda path: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(
        "kh_agent.cli.app._application",
        lambda ctx, db: SimpleNamespace(generate_and_verify=generate_and_verify),
    )
    args = ["modify", "Fix the value", "--target", "app.py", "--model", "local/model"]
    image = "a" * 64
    result = runner.invoke(app, [*args, "--image", image, "--test", "tests/test_app.py"])
    assert result.exit_code == 0, result.output
    assert seen == {
        "target": "app.py",
        "request": "Fix the value",
        "model": "local/model",
        "image": image,
        "tests": ("tests/test_app.py",),
        "port": 1234,
    }
    assert json.loads(result.stdout)["apply_ready"] is False
    for incomplete in (["--image", image], ["--test", "tests/test_app.py"]):
        rejected = runner.invoke(app, [*args, *incomplete])
        assert rejected.exit_code != 0
        assert "must be supplied together" in rejected.output


def test_apply_candidate_routes_reviewed_digest_to_experimental_apply(monkeypatch, tmp_path):
    seen = {}

    def apply_tested_candidate(
        path,
        candidate_file,
        reviewed_hash,
        reviewed_source_hash,
        reviewed_target_digest,
        image,
        tests,
    ):
        seen.update(
            candidate_file=candidate_file,
            reviewed_hash=reviewed_hash,
            reviewed_source_hash=reviewed_source_hash,
            reviewed_target_digest=reviewed_target_digest,
            image=image,
            tests=tests,
        )
        return {"status": "EXPERIMENTAL_APPLIED"}

    monkeypatch.setattr("kh_agent.cli.app.require_linux_store", lambda root: root)
    monkeypatch.setattr(
        "kh_agent.cli.app.Database", lambda path: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(
        "kh_agent.cli.app._application",
        lambda ctx, db: SimpleNamespace(apply_tested_candidate=apply_tested_candidate),
    )
    result = runner.invoke(
        app,
        [
            "apply-candidate",
            str(tmp_path / "candidate.json"),
            "--reviewed-hash",
            "a" * 64,
            "--image",
            "b" * 64,
            "--reviewed-source-hash",
            "c" * 64,
            "--reviewed-target-digest",
            "d" * 64,
            "--test",
            "tests/test_app.py",
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen["reviewed_hash"] == "a" * 64
    assert seen["reviewed_target_digest"] == "d" * 64
    assert seen["tests"] == ("tests/test_app.py",)


def test_reconcile_write_cli_routes_attempt_and_path(monkeypatch, tmp_path):
    seen = {}

    def reconcile_write(path, attempt_id, target):
        seen.update(path=path, attempt_id=attempt_id, target=target)
        return {"status": "WRITE_RECONCILED", "observed": "ORIGINAL_BYTES"}

    monkeypatch.setattr("kh_agent.cli.app.require_linux_store", lambda root: root)
    monkeypatch.setattr(
        "kh_agent.cli.app.Database", lambda path: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(
        "kh_agent.cli.app._application",
        lambda ctx, db: SimpleNamespace(reconcile_write=reconcile_write),
    )
    result = runner.invoke(app, ["reconcile-write", "cmd_" + "a" * 32, "app.py"])
    assert result.exit_code == 0, result.output
    assert seen["target"] == "app.py" and seen["attempt_id"].startswith("cmd_")
