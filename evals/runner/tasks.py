"""Task specs: pinned base commit, issue, hidden fail-to-pass tests and a reference solution."""

import json
from dataclasses import dataclass
from pathlib import Path

FIELDS = {
    "id",
    "source",
    "base_commit",
    "repo_subdir",
    "issue_file",
    "context_files",
    "hidden_tests",
    "fail_to_pass",
    "solution_file",
}


@dataclass(frozen=True)
class Task:
    id: str
    source: str
    base_commit: str
    repo_subdir: str
    issue: str
    context_files: tuple[str, ...]
    # Project-relative destination -> source file inside the task directory.
    hidden_tests: dict[str, Path]
    fail_to_pass: tuple[str, ...]
    solution: Path


def load_task(directory: Path) -> Task:
    spec = json.loads((directory / "task.json").read_text(encoding="utf-8"))
    if set(spec) != FIELDS:
        raise ValueError(f"{directory.name}: task.json fields must be exactly {sorted(FIELDS)}")
    if spec["id"] != directory.name:
        raise ValueError(f"{directory.name}: task id must match its directory name")
    return Task(
        id=spec["id"],
        source=spec["source"],
        base_commit=spec["base_commit"],
        repo_subdir=spec["repo_subdir"],
        issue=(directory / spec["issue_file"]).read_text(encoding="utf-8"),
        context_files=tuple(spec["context_files"]),
        hidden_tests={dest: directory / src for dest, src in spec["hidden_tests"].items()},
        fail_to_pass=tuple(spec["fail_to_pass"]),
        solution=directory / spec["solution_file"],
    )


def load_tasks(tasks_dir: Path, selected: list[str] | None = None) -> list[Task]:
    tasks = [
        load_task(path) for path in sorted(tasks_dir.iterdir()) if (path / "task.json").is_file()
    ]
    if selected:
        unknown = set(selected) - {task.id for task in tasks}
        if unknown:
            raise ValueError(f"Unknown task ids: {sorted(unknown)}")
        tasks = [task for task in tasks if task.id in selected]
    return tasks
