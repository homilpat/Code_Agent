#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo 'Linux validation requires WSL2/Linux.' >&2
  exit 2
fi
if [[ ! -x .venv/bin/python ]]; then
  echo 'Run uv sync --extra dev --locked in code-agent first.' >&2
  exit 2
fi
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m kh_agent doctor
