# Code Agent CLI

Local-first, security-oriented **experimental** coding agent for inspecting and cautiously modifying Python repositories. This repository is now organized as a standalone CLI, not the previous Knowledge Hub blog/web/RAG application.

## Capabilities and limits

- **Implemented**: repository registration, Linux UID-based permissions, audit history, Git worktree inspection, Python AST explanation and impact candidates, sandboxed Pyright queries, local OpenAI-compatible model candidate generation, candidate preview, and bounded rootless Podman pytest.
- **Experimental**: one-existing-Python-file candidate verification and explicitly reviewed worktree replacement; not a formal end-to-end approval pipeline.
- **Not implemented**: autonomous multi-file repair, formal patch apply, web authentication, general-purpose project-wide code generation.
- **Supported stateful runtime**: WSL2/Linux on a local Linux filesystem with the required kernel features. Windows supports development/test tools and `doctor`, not stateful operations.
- **Security note**: this is **not** an OS sandbox for arbitrary LLM tool execution. Do not give it unrestricted credentials or run untrusted code outside its configured isolated execution paths.

## Install and smoke check

```bash
uv sync --extra dev --locked
uv run code-agent --help
uv run code-agent doctor
uv run pytest -q
```

`kh` remains a temporary backwards-compatible alias for existing users. The internal Python import package remains `kh_agent` to avoid destabilizing security-critical imports during the service extraction; it is not a dependency on Knowledge Hub's web services.

## Example

```bash
uv run code-agent init
uv run code-agent repo register /home/user/projects/example
uv run code-agent status --repo /home/user/projects/example
uv run code-agent explain src/example.py --repo /home/user/projects/example
uv run code-agent impact src/example.py --repo /home/user/projects/example
uv run code-agent history --repo /home/user/projects/example
```

To request a candidate from a **locally running** OpenAI-compatible model:

```bash
uv run code-agent modify "Fix the incorrect return value" \
  --target src/example.py --model "$LOCAL_MODEL_ID" --port 1234 \
  --repo /home/user/projects/example
```

The command generates a preview; it does not silently write to the source tree. `verify-candidate`, `apply-candidate`, and `semantic` have explicit image/approval prerequisites. Inspect `code-agent --help` and the source for complete options. Never claim `apply-candidate` constitutes full formal verification.

## Layout

```text
src/kh_agent/          Core CLI engine, access control, Git/snapshot, model, and sandbox
tests/                 Security, unit and integration tests
config/sandbox/        Rootless Podman test and Pyright images
evals/                 Experimental model bug-fixing benchmark (separate trust boundary)
docs/                  CLI migration and retained design requirement reference
.github/workflows/     CI
```

## State migration

Fresh installs default to `~/.code-agent/db/code-agent.db`. Existing `~/.knowledge-hub` stores are discovered and kept readable without copying or deleting user data. Override using `--store` when needed.

See [migration notes](docs/CLI_MIGRATION.md) for the old-to-new directory mapping and retained interfaces.

## Development

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
python -m pytest evals/tests -p no:cacheprovider
```

Design requirement IDs in existing test markers are linked to the preserved historical design document `docs/ARCHITECTURE_DETAILED_DESIGN_v1.10.md`. It is kept as provenance, not as a dependency on the previous web platform.

## License and provenance

No new license is granted by this refactor. The complete pre-extraction implementation and removed web-service files remain accessible in Git history. Review the source and tests before running on valuable repositories.
