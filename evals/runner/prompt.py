"""Model-facing messages. Kept separate so prompt changes are one reviewable diff."""

from pathlib import Path

from evals.runner.edits import EditError
from evals.runner.tasks import Task
from evals.runner.workspace import TestReport

OUTPUT_TAIL = 6000

SYSTEM_PROMPT = """\
You fix bugs in a Python project. You cannot run commands. A harness applies your edits and then \
runs the whole test suite, including tests you have not seen.

Answer with SEARCH/REPLACE blocks. You may write a short explanation first. Block format:

path/relative/to/project.py
<<<<<<< SEARCH
existing lines copied exactly from the current file
=======
replacement lines
>>>>>>> REPLACE

Rules:
- Put the file path on the line directly above each block, relative to the project root.
- SEARCH must match the current file exactly once. Include enough unchanged lines to be unique.
- An empty SEARCH section creates a new file.
- Use several blocks for several changes. Keep the change minimal.
- Do not modify or delete existing tests.
"""

REASONS = {
    "TEST_FAIL": "The issue is not fixed yet: required tests still fail.",
    "REGRESSION": "The required tests pass, but other tests now fail.",
    "TIMEOUT": "The test run timed out.",
}


def initial_messages(task: Task, project: Path) -> list[dict]:
    parts = [f"## Issue\n\n{task.issue.strip()}", "## Files"]
    parts.extend(_file_section(project, relative) for relative in task.context_files)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def edit_failure_feedback(error: EditError, project: Path, changed: dict) -> str:
    return "\n\n".join(
        [
            f"Your reply could not be applied ({error.category}): {error.message}\n"
            "None of the blocks in that reply were applied.",
            *_changed_files(project, changed),
            "Reply with corrected SEARCH/REPLACE blocks.",
        ]
    )


def test_failure_feedback(verdict: str, report: TestReport, project: Path, changed: dict) -> str:
    return "\n\n".join(
        [
            f"Your edits were applied. {REASONS[verdict]}",
            f"Test output (tail):\n````\n{report.output[-OUTPUT_TAIL:]}\n````",
            *_changed_files(project, changed),
            "Reply with further SEARCH/REPLACE blocks against the current file contents.",
        ]
    )


def _changed_files(project: Path, changed: dict) -> list[str]:
    if not changed:
        return []
    return [
        "## Current content of the files you changed",
        *(_file_section(project, relative) for relative in sorted(changed)),
    ]


def _file_section(project: Path, relative: str) -> str:
    path = project / relative
    content = path.read_bytes().decode("utf-8") if path.exists() else "(file does not exist)\n"
    if not content.endswith("\n"):
        content += "\n"
    return f"### {relative}\n````\n{content}````"
