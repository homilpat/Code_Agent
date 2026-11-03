# Standalone CLI extraction

This branch extracts the already implemented Code Agent CLI from a monorepo that also contained the unrelated Knowledge Hub Spring/Next.js/RAG blog application.

## What moved

| Previous path | Current path |
|---|---|
| `code-agent/src/kh_agent/` | `src/kh_agent/` |
| `code-agent/tests/` | `tests/` |
| `code-agent/config/` | `config/` |
| `code-agent/pyproject.toml` | `pyproject.toml` |
| `code-agent/uv.lock` | `uv.lock` |
| `evals/` | `evals/` (retained) |

Removed from the current branch: `backend-spring/`, `frontend-nextjs/`, `rag-fastapi/`, `docker/`, `게시물/`, previous project Docker compose configuration and their supporting project docs. The old Git commits are intentionally **not rewritten**.

## Compatibility and safety

- Installed package distribution is now `code-agent-cli`.
- Executable is `code-agent`; `kh` remains as a temporary compatibility command.
- Internal import namespace stays `kh_agent` during this extraction to avoid unnecessary high-risk bulk changes.
- Fresh default state path: `~/.code-agent`, SQLite file `db/code-agent.db`.
- Existing `~/.knowledge-hub` state remains readable by default and an existing `db/knowledge-hub.db` takes precedence. No automatic migration, overwrite, or deletion.
- To use a fresh store when an old one exists, explicitly pass `--store ~/.code-agent`.
- `docs/ARCHITECTURE_DETAILED_DESIGN_v1.10.md` is retained **solely as historical test-ID provenance**; new requirements should be authored separately.
- Benchmark task manifests may intentionally reference the old `code-agent/` directory inside a pinned **historical Git commit**. Do not rewrite their source history or expected answers.

## Release gates

Run `uv sync --extra dev --locked`, `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, plus Linux Podman integration tests using actual rootless Podman. CI runs all required checks; merge only after evidence of green checks. If they fail, fix the root cause, do not weaken tests.

The change is a **service extraction**, not a claim of a fully autonomous agent or final security certification.
