import pytest

from evals.runner.__main__ import TASKS_DIR
from evals.runner.edits import parse_edits
from evals.runner.run import failure_cause
from evals.runner.tasks import load_tasks

SOLUTION = {"src/pkg/fix.py"}


@pytest.mark.parametrize(
    "verdict, edited, cause",
    [
        ("PASS", {"src/pkg/fix.py"}, None),
        ("FORMAT_ERROR", set(), "FORMAT"),
        ("TRUNCATED", set(), "FORMAT"),
        ("APPLY_ERROR", {"src/pkg/fix.py"}, "FORMAT"),
        ("APPLY_ERROR", {"src/other.py"}, "LOCALIZATION"),
        ("APPLY_ERROR", set(), "FORMAT"),
        ("TEST_FAIL", {"src/other.py"}, "LOCALIZATION"),
        ("TEST_FAIL", {"src/pkg/fix.py", "src/other.py"}, "LOGIC"),
        ("REGRESSION", {"src/pkg/fix.py"}, "LOGIC"),
        ("LLM_ERROR", set(), "MODEL_CALL"),
        ("HARNESS_ERROR", set(), "TEST_ENVIRONMENT"),
        ("TIMEOUT", {"src/pkg/fix.py"}, "UNDETERMINED"),
        ("NO_ATTEMPT", set(), "UNDETERMINED"),
    ],
)
def test_failure_cause_comes_from_the_verdict_and_edited_files(verdict, edited, cause):
    assert failure_cause(verdict, edited, SOLUTION) == cause


def test_every_reference_solution_names_project_relative_files():
    for task in load_tasks(TASKS_DIR):
        paths = {edit.path for edit in parse_edits(task.solution.read_text(encoding="utf-8"))}
        assert paths, task.id
        assert not any(path.startswith(("/", "..")) or ":" in path for path in paths), task.id
