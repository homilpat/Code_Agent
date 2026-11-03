# Code Agent CLI

**A local-first, security-oriented coding agent for inspecting Python repositories and testing explicit code changes.**

[English](README.md) | [한국어](README.ko.md)

**Status:** Experimental v0.1.0 · **License:** [Apache-2.0](LICENSE) · **Author:** JongHyeok Jang ([@homilpat](https://github.com/homilpat))

Code Agent CLI integrates repository-aware inspection, local identity and access control, auditable state, source analysis, local-model-assisted patch proposals, and bounded container verification. It favors **inspect → propose → review → verify → explicitly apply** over unrestricted autonomous execution.

> **Scope:** This is an experimental Python-focused CLI—not a production-ready autonomous multi-file coding agent or a general sandbox for arbitrary model-generated commands.

## Why this project?

A code-generating model can propose a plausible change without proving that the right repository, file version, privileges, and test environment were used. Code Agent CLI explores **verifiable coding workflows**: tie requests to a registered Git repository, limit source operations to authorized users, keep audit metadata, and verify candidate changes inside rootless Podman before an explicit single-file write.

The project was extracted from a larger Knowledge Hub monorepo. The standalone CLI **does not require** its former Spring Boot, Next.js, MySQL, or RAG services.

## Features and implementation status

| Area | Current capability | Status |
| --- | --- | --- |
| CLI and setup | `doctor`, `init`, repository registration, CLI help | Implemented |
| Identity and permissions | Linux UID-based local identity, repository ACL grants/revocations | Implemented |
| Repository inspection | Git HEAD/index/worktree checks; clean-state and integrity checks | Implemented |
| Audit and state | Local SQLite metadata, history, verification state | Implemented |
| Python source understanding | AST-based `explain` and import-candidate `impact` | Partial |
| Semantic analysis | Pyright queries within a configured rootless Podman sandbox | Implemented with prerequisites |
| Local model proposal | `modify` using a loaded local OpenAI-compatible model | Experimental |
| Candidate review | `preview-candidate` without modifying source | Implemented |
| Candidate verification | `verify-candidate` runs registered pytest tests in rootless Podman | Experimental |
| Explicit source replacement | `apply-candidate` requires reviewed hashes and fresh isolated tests; one existing Python file | Experimental |
| Autonomous multi-file repair, formal approval flow, web auth, general optimization | Not delivered | Not available |

Commands such as `profile`, `optimize`, `verify`, and `apply` are currently **reserved**. A command appearing in `--help` does not mean its full workflow has been implemented.

## Requirements

- Python **3.11+** and [uv](https://docs.astral.sh/uv/)
- **WSL2/Linux**, with the trusted state store on a local Linux **ext4, XFS, or Btrfs** filesystem
- Git for repository operations
- **Rootless Podman** and prebuilt, explicitly identified container images for sandboxed tests and Pyright
- A locally hosted OpenAI-compatible language model **only if** using model-backed `modify`

Native Windows supports development checks and `doctor`, **not stateful repository operations**. Avoid storing the trusted state database on network mounts or WSL Windows drives such as `/mnt/c`.

## Quick start

Clone the **standalone CLI branch** until PR #1 is merged:

```bash
git clone --branch refactor/standalone-code-agent-cli https://github.com/homilpat/Code_Agent.git
cd Code_Agent
uv sync --extra dev --locked

uv run code-agent --help
uv run code-agent doctor
```

The repository is currently private; cloning requires authorized GitHub access. Python dependencies install locally; no web-service stack is required.

On supported Linux/WSL2, initialize the trusted store, register a separate Git repository, and inspect it:

```bash
uv run code-agent init
uv run code-agent repo register /home/user/projects/example
uv run code-agent status --repo /home/user/projects/example
uv run code-agent explain src/example.py --repo /home/user/projects/example
uv run code-agent impact src/example.py --repo /home/user/projects/example
uv run code-agent history --repo /home/user/projects/example
```

The target repository must exist, be eligible under the tool's filesystem and Git safety checks, and be registered first. The state store must remain **outside** the target repository. `explain` and `impact` operate on Python source paths relative to that registered repository.

### Local-model candidate generation

Start an OpenAI-compatible model server **locally**, then supply the loaded model identifier and file target:

```bash
uv run code-agent modify "Fix the incorrect return value" \
  --target src/example.py \
  --model "$LOCAL_MODEL_ID" \
  --port 1234 \
  --repo /home/user/projects/example
```

Without an image/test pair, this requests a **preview**, not an automatic source write. If you supply `--image`, you must also supply at least one `--test`. Model identifiers, test registrations, and sandbox image prerequisites are environment-specific; see `uv run code-agent modify --help`.

### Verification and guarded apply

```bash
uv run code-agent preview-candidate --help
uv run code-agent verify-candidate --help
uv run code-agent apply-candidate --help
uv run code-agent semantic --help
```

The explicit single-file apply path requires reviewed candidate/source/target hashes, a prebuilt immutable image, and a fresh isolated pytest run. **Do not treat a passing test as proof of functional correctness or security.** No unreviewed, autonomous write is promised.

## Trust and security boundaries

- Local identity is bound to a Linux OS principal, with repository-scoped permissions.
- Repository inspection detects relevant worktree and Git-state changes; mutation operations may refuse unsafe or incomplete state.
- The trusted local database stores **audit metadata**, not arbitrary model chat logs, and is subject to filesystem restrictions.
- Rootless Podman restricts the specific verification/semantic execution paths. **The separate `evals/` runner executes trusted benchmark tests on the host and is not protected by the product sandbox.**
- A local model endpoint is not a guarantee that model inputs are harmless: review source content and configuration before using a server.
- This tool does **not** sandbox arbitrary shell commands, guarantee secrets cannot leak, or replace independent security review.

## Repository structure

```text
Code_Agent/
├── src/kh_agent/           # Current Python import package (legacy name)
├── tests/                  # Agent unit, security and integration tests
├── config/sandbox/         # Rootless Podman image definitions
├── evals/                  # Separate research benchmark runner and tasks
├── scripts/                # Linux verification helper
├── docs/                   # CLI migration + preserved design/test-ID provenance
├── .github/workflows/      # CI
├── pyproject.toml
├── uv.lock
├── README.md
├── README.ko.md
├── LICENSE
├── NOTICE
└── CITATION.cff
```

The package's internal name is still `kh_agent` to preserve existing imports; the distribution and preferred command are `code-agent-cli` and `code-agent`. `kh` remains a temporary compatibility command.

## Tests and reproducibility

Run from the repository root:

```bash
uv sync --extra dev --locked
uv run pytest -q
uv run python -m pytest -q evals/tests -p no:cacheprovider
uv run ruff check .
uv run ruff format --check src tests evals
```

GitHub Actions additionally builds pinned sandbox images and runs real rootless Podman/Pyright integration tests. An earlier verified CI run recorded **9 integration tests passed**, **255 core tests passed (1 platform-specific skip)**, **32 eval runner tests passed**, and clean Ruff checks. These are **test outcomes, not coding-agent benchmark success rates**. See [GitHub Actions](https://github.com/homilpat/Code_Agent/actions) for the current branch result.

### Research evaluation

`evals/` is a **separate experimental harness**, not an enforcement boundary. It exports pinned historical Git snapshots, invokes a local model, applies exact SEARCH/REPLACE edits in temporary workspaces, reruns hidden tests, and records outcomes including regression and flaky tests.

```bash
uv run python -m evals.runner validate
uv run python -m evals.runner run --model YOUR_LOCAL_MODEL_ID --attempts 3
```

The runner requires a suitable local model server for `run` and executes benchmark tests **on the host**. Use **trusted benchmark tasks only**. Current evaluation coverage is small; do not extrapolate research results from it. See [evals/README.md](evals/README.md).

## Legacy data and migration

New installations use `~/.code-agent/db/code-agent.db`; if `~/.knowledge-hub` already exists, that legacy store may be selected, including its `db/knowledge-hub.db`. No automatic data deletion or database migration is performed. Use the global `--store` option to select a different trusted store. See [migration notes](docs/CLI_MIGRATION.md).

## Roadmap

Planned research directions—not current features—include clearer agent-policy experiments, more benchmark tasks, measurable security-versus-task-success trade-offs, and a separately tested migration of the internal `kh_agent` namespace.

## License, citation and provenance

Copyright © 2026 **JongHyeok Jang**. Licensed under the **[Apache License 2.0](LICENSE)**. Keep applicable copyright/license notices and identify modified files when redistributing; see [NOTICE](NOTICE). Dependencies retain their own license obligations.

If this project supports your academic work, **please cite it** using [CITATION.cff](CITATION.cff). Academic citation is requested but **not an additional legal requirement** under Apache 2.0.

This license covers the standalone CLI branch as presented here; removed Knowledge Hub application source in older Git commits is **not automatically relicensed** by these files. Community contributions or external code require appropriate rights and attribution.
