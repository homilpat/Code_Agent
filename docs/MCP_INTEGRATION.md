# Code Agent as a local MCP server

Code Agent also exposes **MCP tools** to compatible host applications. The MCP server is an adapter around the existing security-aware CLI; it is **not an unrestricted shell** and does not replace the CLI's Linux UID identity, repository registration, ACL, safe Git checks, or audit history.

## Installation

Install the normal project as documented in the main README. The MCP SDK is opt-in so that ordinary CLI installs and the existing locked dependencies remain unchanged.

```bash
uv sync --extra dev --locked
uv run --with 'mcp>=2,<3' python -m kh_agent.mcp_server
```

The process runs on **stdio**. A terminal appears to hang because it is waiting for MCP requests, not because it has started a web server. No remote HTTP listener is opened.

## Host configuration

Example host config (replace `/absolute/path/to/Code_Agent` with the checkout and use a Linux/WSL2 home directory):

```json
{
  "mcpServers": {
    "code-agent": {
      "command": "uv",
      "args": [
        "run", "--project", "/absolute/path/to/Code_Agent",
        "--with", "mcp>=2,<3",
        "python", "-m", "kh_agent.mcp_server"
      ]
    }
  }
}
```

MCP hosts differ in their configuration format and tool policy. Run the host application **inside the same WSL2/Linux environment** as the CLI when stateful operations are required, and ensure `uv` is installed on its executable PATH.

For a custom existing trusted store, append `--store` and an **absolute** path to the args. Do not put credentials in MCP config.

## Tools

| MCP tool | CLI backend | Scope |
| --- | --- | --- |
| `repository_status` | `status` | Registered Git status and integrity signals |
| `audit_history` | `history` | Authorized audit metadata (last 100 records) |
| `explain_python` | `explain` | AST-based Python explanation |
| `impact_candidates` | `impact` | Import candidates; no confirmed risk score |
| `propose_python_change` | `modify` | Local LLM candidate **preview only** |

Each tool requires an **absolute registered repository path**. Analysis and proposal tools also require a Python file path **relative to the repository**. Register repositories through the trusted CLI first:

```bash
uv run code-agent init
uv run code-agent repo register /home/user/projects/example
```

The local model tool additionally needs a running **OpenAI-compatible** inference API on `127.0.0.1`, with a loaded model name and port. The current backend uses `/v1/chat/completions`; native provider-specific Ollama endpoints require an OpenAI-compatible bridge. The MCP client/host must support invoking tools; merely running a model does **not** make it an MCP host.

## Security boundary

- No `apply`, arbitrary command execution, file deletion, project registration, or permission-changing tools are exposed.
- Only registered repositories are usable, through the regular Code Agent authorization path. MCP caller-controlled input must **not** become the OS authority.
- `propose_python_change` only previews a candidate. Apply remains the separate, explicit CLI review/verification procedure.
- Calls may still disclose authorized source analysis or audit **metadata** to the host application. Trust your MCP host and review its privacy policy.
- This is a local stdio server; the host that launches it inherits the OS user's permissions. The server does not provide separate per-client network authentication.
- Tool responses are bounded and raw CLI stderr is not exposed.

**Compatibility:** Any host implementing standard MCP stdio tool calls can connect. This does not mean every local LLM runtime automatically supports MCP; use an MCP-capable host or agent orchestrator.

Official SDK guidance: https://py.sdk.modelcontextprotocol.io/run/
