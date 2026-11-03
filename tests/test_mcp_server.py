"""MCP adapter tests run without requiring the optional MCP SDK."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from kh_agent.mcp_server import _absolute_repo, _target_path, execute_cli


def test_only_allowlisted_tools_are_callable(monkeypatch):
    invoked = Mock()
    monkeypatch.setattr(subprocess, "run", invoked)
    assert execute_cli("apply", "/home/testuser/repo") == {"ok": False, "error": "UNSUPPORTED_TOOL"}
    invoked.assert_not_called()


@pytest.mark.parametrize("repo", ["relative/repo", "", "../repo", "/home/testuser/repo\nrun"])
def test_rejects_nonabsolute_or_control_character_paths(repo):
    assert execute_cli("status", repo) == {"ok": False, "error": "INVALID_ARGUMENT"}


@pytest.mark.parametrize("target", ["/etc/passwd", "--help", "a.py\nfoo", ""])
def test_rejects_invalid_source_targets(target):
    assert execute_cli("explain", "/home/testuser/repo", target=target) == {
        "ok": False, "error": "INVALID_ARGUMENT"
    }


def test_mcp_delegates_to_existing_cli_and_acl(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args, 0, json.dumps({"repository_id": "r1"}).encode(), b""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = execute_cli(
        "explain", "/home/testuser/repo", store="/home/testuser/trusted", target="src/a.py"
    )
    assert result == {"ok": True, "data": {"repository_id": "r1"}}
    assert captured["args"][1:5] == ["-m", "kh_agent", "--store", "/home/testuser/trusted"]
    assert captured["args"][-4:] == ["explain", "src/a.py", "--repo", "/home/testuser/repo"]
    assert captured["kwargs"]["capture_output"] is True
    assert "shell" not in captured["kwargs"]


def test_cli_access_denial_is_not_swallowed(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 3, b"", b'{"error":"ACCESS_DENIED","message":"Sensitive path"}'
        ),
    )
    assert execute_cli("status", "/home/testuser/repo") == {"ok": False, "error": "ACCESS_DENIED"}


def test_mcp_never_returns_raw_errors_or_secrets(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 1, b"", b"Sensitive token in subprocess stderr"
        ),
    )
    assert execute_cli("history", "/home/testuser/repo") == {"ok": False, "error": "CLI_FAILED"}


def test_mcp_modify_has_no_automatic_apply(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, b'{"preview":"generated"}', b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = execute_cli(
        "modify", "/home/testuser/repo", target="code.py", model="local-model", request="Fix bug"
    )
    assert result["ok"]
    assert captured["args"].count("modify") == 1
    assert "apply-candidate" not in captured["args"]
    assert "--image" not in captured["args"]


def test_model_port_and_input_limits():
    assert execute_cli(
        "modify", "/home/testuser/repo", target="a.py", request="ok", model="model", port=0
    ) == {"ok": False, "error": "INVALID_ARGUMENT"}
    assert execute_cli(
        "modify", "/home/testuser/repo", target="a.py", request="A" * 4001, model="model"
    ) == {"ok": False, "error": "INVALID_ARGUMENT"}


def test_backend_boundaries_not_replaced():
    assert _absolute_repo("/home/testuser/example") == "/home/testuser/example"
    assert _target_path("src/a.py") == "src/a.py"
    assert Path("/home/testuser/example").is_absolute()
