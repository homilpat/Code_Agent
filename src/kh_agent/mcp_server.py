"""MCP stdio adapter for the existing Code Agent CLI security boundary.

No LLM, shell, or repository command is executed directly by this server.
All tools delegate to the installed Code Agent CLI, preserving its identity,
repository ACL, source ingestion, and audit checks.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_OUTPUT_BYTES = 256 * 1024
MAX_PATH_CHARS = 4096


def _absolute_repo(repo: str) -> str:
    if (
        type(repo) is not str
        or not 1 <= len(repo) <= MAX_PATH_CHARS
        or any(ord(ch) < 32 for ch in repo)
        or not Path(repo).is_absolute()
    ):
        raise ValueError("Repository must be an absolute local path")
    return repo


def _target_path(target: str) -> str:
    if (
        type(target) is not str
        or not 1 <= len(target) <= 1024
        or any(ord(ch) < 32 for ch in target)
        or target.startswith("-")
        or Path(target).is_absolute()
    ):
        raise ValueError("Target must be a relative Python source path")
    return target


def execute_cli(
    command: str,
    repo: str,
    *,
    store: str | None = None,
    target: str | None = None,
    request: str | None = None,
    model: str | None = None,
    port: int = 1234,
) -> dict[str, Any]:
    """Call only selected CLI operations; do not expose arbitrary command execution."""
    if command not in {"status", "history", "explain", "impact", "modify"}:
        return {"ok": False, "error": "UNSUPPORTED_TOOL"}
    try:
        repo = _absolute_repo(repo)
        if command in {"explain", "impact", "modify"}:
            target = _target_path(target)
        if command == "modify":
            if (
                type(request) is not str
                or not 1 <= len(request) <= 4000
                or type(model) is not str
                or not 1 <= len(model) <= 128
                or type(port) is not int
                or not 1 <= port <= 65535
            ):
                raise ValueError("Invalid local model request")
        args = [sys.executable, "-m", "kh_agent"]
        if store is not None:
            if type(store) is not str or not Path(store).is_absolute():
                raise ValueError("Trusted store must be an absolute path")
            args.extend(["--store", store])
        args.append(command)
        if command in {"explain", "impact"}:
            args.append(target)
        elif command == "modify":
            args.extend([request, "--target", target, "--model", model, "--port", str(port)])
        args.extend(["--repo", repo])
        completed = subprocess.run(  # noqa: S603 - fixed interpreter, module and allowlisted argv
            args,
            capture_output=True,
            timeout=240 if command == "modify" else 90,
            check=False,
        )
        if len(completed.stdout) > MAX_OUTPUT_BYTES or len(completed.stderr) > MAX_OUTPUT_BYTES:
            return {"ok": False, "error": "OUTPUT_TOO_LARGE"}
        if completed.returncode != 0:
            # CLI failures may contain local paths. Return trusted error codes only.
            try:
                error = json.loads(completed.stderr.decode("utf-8"))
                code = error.get("error")
            except (ValueError, UnicodeError, AttributeError):
                code = None
            return {
                "ok": False,
                "error": code if type(code) is str and code.isupper() else "CLI_FAILED",
            }
        result = json.loads(completed.stdout.decode("utf-8"))
        return {"ok": True, "data": result}
    except ValueError:
        return {"ok": False, "error": "INVALID_ARGUMENT"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "TIMEOUT"}
    except (OSError, UnicodeError, TypeError, json.JSONDecodeError):
        return {"ok": False, "error": "CLI_UNAVAILABLE"}


def create_server(*, store: str | None = None):
    """Create the official Python MCP SDK server. SDK is an opt-in dependency."""
    try:
        from mcp.server import MCPServer
    except ImportError as exc:
        raise RuntimeError(
            'MCP SDK missing: start with uv run --with "mcp>=2,<3" '
            'python -m kh_agent.mcp_server'
        ) from exc

    server = MCPServer(
        "code-agent",
        instructions=(
            "Local-only Code Agent tools. Only registered repositories can be inspected. "
            "Tools use OS identity and existing Code Agent ACLs. "
            "Model-generated changes are previews and never automatically applied."
        ),
    )

    @server.tool()
    def repository_status(repository: str) -> dict[str, Any]:
        """Inspect authorized Git state for an explicitly registered absolute repository path."""
        return execute_cli("status", repository, store=store)

    @server.tool()
    def audit_history(repository: str) -> dict[str, Any]:
        """Read up to 100 authorized Code Agent audit metadata events."""
        return execute_cli("history", repository, store=store)

    @server.tool()
    def explain_python(repository: str, target: str) -> dict[str, Any]:
        """Explain Python definitions/imports/calls for a registered repository."""
        return execute_cli("explain", repository, store=store, target=target)

    @server.tool()
    def impact_candidates(repository: str, target: str) -> dict[str, Any]:
        """List candidate Python import impacts; not a verified risk score."""
        return execute_cli("impact", repository, store=store, target=target)

    @server.tool()
    def propose_python_change(
        repository: str, target: str, request: str, model: str, port: int = 1234
    ) -> dict[str, Any]:
        """Ask a local loopback OpenAI-compatible model for a preview; never write source."""
        return execute_cli(
            "modify",
            repository,
            store=store,
            target=target,
            request=request,
            model=model,
            port=port,
        )

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Code Agent local stdio MCP server")
    parser.add_argument("--store", type=Path, default=None, help="Absolute trusted-store path")
    args = parser.parse_args(argv)
    if args.store is not None and not args.store.is_absolute():
        parser.error("--store must be absolute")
    create_server(store=str(args.store) if args.store else None).run(transport="stdio")


if __name__ == "__main__":
    main()
