"""Task validation (is the task solvable and does it fail at base?) and the model edit loop."""

import difflib
import time
from pathlib import Path, PurePosixPath

from evals.runner.edits import EditError, apply_edits, parse_edits
from evals.runner.llm import ChatClient, LLMError
from evals.runner.prompt import edit_failure_feedback, initial_messages, test_failure_feedback
from evals.runner.tasks import Task
from evals.runner.workspace import TestReport, Workspace


def judge(task: Task, report: TestReport) -> str:
    if report.timed_out:
        return "TIMEOUT"
    if not all(_satisfied(spec, report) for spec in task.fail_to_pass):
        return "TEST_FAIL"
    if report.failed:
        return "REGRESSION"
    return "PASS"


def failure_cause(verdict: str, edited: set[str], solution_files: set[str]) -> str | None:
    """Which part of the loop to improve, derived from the verdict and edited files only.

    LOCALIZATION: every edited file lies outside the reference solution (wrong place).
    FORMAT: an unparseable or truncated reply, or SEARCH text that does not match its file.
    LOGIC: a solution file was edited but required tests still fail or others regress.
    TEST_ENVIRONMENT / MODEL_CALL: harness or model endpoint failures.
    UNDETERMINED: a timeout or no attempt cannot be attributed without more evidence.
    The reference solution is one valid fix, so LOCALIZATION is only assigned to failures.
    """
    if verdict == "PASS":
        return None
    if verdict in {"FORMAT_ERROR", "TRUNCATED"}:
        return "FORMAT"
    if verdict in {"APPLY_ERROR", "TEST_FAIL", "REGRESSION"}:
        if edited and not edited & solution_files:
            return "LOCALIZATION"
        return "FORMAT" if verdict == "APPLY_ERROR" else "LOGIC"
    if verdict == "LLM_ERROR":
        return "MODEL_CALL"
    if verdict == "HARNESS_ERROR":
        return "TEST_ENVIRONMENT"
    return "UNDETERMINED"


def validate(repo_root: Path, task: Task, python: str, timeout: int, keep: bool) -> dict:
    workspace = Workspace(repo_root, task)
    problems = []
    flaky: set[str] = set()
    try:
        workspace.check_import_isolation(python)
        base = workspace.run_tests(python, timeout)
        if base.timed_out:
            problems.append("base test run timed out")
        passing = [spec for spec in task.fail_to_pass if _satisfied(spec, base)]
        if passing:
            problems.append(f"fail_to_pass tests already pass at base: {passing}")
        unexpected = sorted(
            test for test in base.failed if not any(_matches(test, s) for s in task.fail_to_pass)
        )
        if unexpected:
            problems.append(f"unexpected failures at base: {unexpected}")
        flaky |= base.flaky
        apply_edits(workspace.project, parse_edits(task.solution.read_text(encoding="utf-8")))
        fixed = workspace.run_tests(python, timeout)
        flaky |= fixed.flaky
        verdict = judge(task, fixed)
        if verdict != "PASS":
            problems.append(f"reference solution verdict {verdict}:\n{fixed.output[-3000:]}")
    except EditError as exc:
        problems.append(f"reference solution {exc.category}: {exc.message}")
    except RuntimeError as exc:
        problems.append(str(exc))
    finally:
        if not keep:
            workspace.remove()
    return {"task_id": task.id, "valid": not problems, "problems": problems, "flaky": sorted(flaky)}


def solve(
    repo_root: Path,
    task: Task,
    client: ChatClient,
    python: str,
    attempts: int,
    timeout: int,
    keep: bool,
) -> dict:
    workspace = Workspace(repo_root, task)
    started = time.monotonic()
    originals: dict[str, str | None] = {}
    log: list[dict] = []
    verdict = "NO_ATTEMPT"
    try:
        solution = parse_edits(task.solution.read_text(encoding="utf-8"))
        solution_files = {
            PurePosixPath(edit.path.replace("\\", "/")).as_posix() for edit in solution
        }
        workspace.check_import_isolation(python)
        messages = initial_messages(task, workspace.project)
        for attempt in range(1, attempts + 1):
            entry: dict = {"attempt": attempt}
            log.append(entry)
            try:
                completion = client.complete(messages)
            except LLMError as exc:
                verdict = "LLM_ERROR"
                entry.update(verdict=verdict, detail=str(exc), cause="MODEL_CALL")
                break
            entry.update(
                llm_seconds=round(completion.seconds, 1),
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                finish_reason=completion.finish_reason,
            )
            messages.append({"role": "assistant", "content": completion.text})
            try:
                previous = apply_edits(workspace.project, parse_edits(completion.text))
            except EditError as exc:
                truncated = exc.category == "FORMAT_ERROR" and completion.finish_reason == "length"
                verdict = "TRUNCATED" if truncated else exc.category
                entry.update(
                    verdict=verdict,
                    detail=exc.message,
                    cause=failure_cause(verdict, {exc.path} if exc.path else set(), solution_files),
                )
                messages.append(
                    {
                        "role": "user",
                        "content": edit_failure_feedback(exc, workspace.project, originals),
                    }
                )
                continue
            for relative, content in previous.items():
                originals.setdefault(relative, content)
            report = workspace.run_tests(python, timeout)
            verdict = judge(task, report)
            entry.update(
                verdict=verdict,
                test_seconds=round(report.seconds, 1),
                failed=sorted(report.failed)[:20],
                flaky=sorted(report.flaky),
                cause=failure_cause(verdict, set(previous), solution_files),
            )
            if verdict == "PASS":
                break
            messages.append(
                {
                    "role": "user",
                    "content": test_failure_feedback(verdict, report, workspace.project, originals),
                }
            )
        diff = _diff(workspace.project, originals)
    except (RuntimeError, EditError) as exc:  # EditError here means an unusable reference solution
        verdict = "HARNESS_ERROR"
        log.append({"verdict": verdict, "detail": str(exc), "cause": "TEST_ENVIRONMENT"})
        diff = ""
    finally:
        if not keep:
            workspace.remove()
    return {
        "task_id": task.id,
        "model": client.model,
        "success": verdict == "PASS",
        "verdict": verdict,
        "failure_cause": None
        if verdict == "PASS"
        else next((entry["cause"] for entry in reversed(log) if "cause" in entry), "UNDETERMINED"),
        "attempts_used": sum(1 for entry in log if "attempt" in entry),
        "seconds": round(time.monotonic() - started, 1),
        "touched_tests": any(path.startswith("tests/") for path in originals),
        "attempts": log,
        "diff": diff,
    }


def _matches(test_id: str, spec: str) -> bool:
    return test_id == spec or test_id.startswith(spec + "[")


def _satisfied(spec: str, report: TestReport) -> bool:
    """A fail-to-pass spec holds when it ran, every parametrization passed and none was skipped."""
    ran = [t for t in report.passed if _matches(t, spec)]
    bad = [t for t in report.failed | report.skipped if _matches(t, spec)]
    return bool(ran) and not bad


def _diff(project: Path, originals: dict[str, str | None]) -> str:
    chunks = []
    for relative, before in sorted(originals.items()):
        path = project / relative
        after = path.read_bytes().decode("utf-8") if path.exists() else ""
        chunks.extend(
            difflib.unified_diff(
                (before or "").splitlines(keepends=True),
                after.splitlines(keepends=True),
                f"a/{relative}",
                f"b/{relative}",
            )
        )
    return "".join(chunks)
