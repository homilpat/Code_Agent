import json
import sys

import pytest
from typer.testing import CliRunner

from kh_agent.cli.app import app

runner = CliRunner()


def test_help_and_doctor_do_not_require_linux():
    assert runner.invoke(app, ["--help"]).exit_code == 0
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["sandbox"] == "NOT_AVAILABLE"
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
