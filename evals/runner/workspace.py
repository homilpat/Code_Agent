"""Throwaway task workspaces exported from a pinned commit, and pytest execution inside them."""

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path

from evals.runner.tasks import Task

NO_REPORT = "<pytest produced no report>"


@dataclass
class TestReport:
    passed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    flaky: set[str] = field(default_factory=set)
    output: str = ""
    seconds: float = 0.0
    timed_out: bool = False


class Workspace:
    def __init__(self, repo_root: Path, task: Task, work_root: Path | None = None):
        self.task = task
        self.root = Path(tempfile.mkdtemp(prefix=f"{task.id}-", dir=work_root))
        # autocrlf off: the workspace must hold the committed bytes, not Windows checkout bytes.
        archive = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "-c",
                "core.autocrlf=false",
                "archive",
                "--format=tar",
                task.base_commit,
                task.repo_subdir,
            ],
            capture_output=True,
            check=True,
        )
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(self.root, filter="data")
        self.project = self.root / task.repo_subdir

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "PYTHONPATH": str(self.project / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }

    def check_import_isolation(self, python: str) -> None:
        """Refuse to run if the interpreter would import the package from outside this workspace,
        e.g. through an editable install that shadows PYTHONPATH."""
        for package in (self.project / "src").iterdir():
            if not (package / "__init__.py").is_file():
                continue
            completed = subprocess.run(
                [python, "-c", f"import {package.name}; print({package.name}.__file__)"],
                cwd=self.project,
                env=self.env(),
                capture_output=True,
                text=True,
                timeout=60,
            )
            location = completed.stdout.strip()
            if completed.returncode != 0 or not Path(location).resolve().is_relative_to(
                self.project.resolve()
            ):
                raise RuntimeError(
                    f"{package.name} imports from {location or completed.stderr.strip()!r}, "
                    "not from the task workspace"
                )

    def run_tests(self, python: str, timeout: int, reruns: int = 2) -> TestReport:
        # Reinstalled before every run so a model edit cannot replace the hidden tests.
        for destination, source in self.task.hidden_tests.items():
            target = self.project / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        started = time.monotonic()
        report = self._pytest(python, timeout, [])
        # Some target tests are timing-flaky on Windows (stat ctime lag), so rerun only the
        # failures. Recovered tests are reported as flaky rather than silently counted as passing.
        for _ in range(reruns):
            if report.timed_out or not report.failed or NO_REPORT in report.failed:
                break
            retry = self._pytest(python, timeout, sorted(report.failed))
            recovered = report.failed & retry.passed
            report.failed -= recovered
            report.passed |= recovered
            report.flaky |= recovered
            if retry.failed or retry.timed_out:
                report.output = retry.output
        report.seconds = time.monotonic() - started
        return report

    def _pytest(self, python: str, timeout: int, selection: list[str]) -> TestReport:
        junit = self.root / "junit.xml"
        junit.unlink(missing_ok=True)
        command = [
            python,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(self.root / "pytest-tmp"),
            f"--junitxml={junit}",
            *selection,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.project,
                env=self.env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return TestReport(output=_text(exc.stdout), timed_out=True)
        report = _parse_junit(junit) if junit.exists() else TestReport(failed={NO_REPORT})
        report.output = completed.stdout + completed.stderr
        return report

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def _parse_junit(path: Path) -> TestReport:
    report = TestReport()
    for case in ElementTree.parse(path).iter("testcase"):
        test_id = _node_id(case.get("classname", ""), case.get("name", ""))
        if case.find("failure") is not None or case.find("error") is not None:
            report.failed.add(test_id)
        elif case.find("skipped") is not None:
            report.skipped.add(test_id)
        else:
            report.passed.add(test_id)
    return report


def _node_id(classname: str, name: str) -> str:
    """Map junit ``tests.test_x[.TestClass]`` + name back to a pytest-style node id."""
    parts = classname.split(".")
    klass = parts.pop() if parts and parts[-1][:1].isupper() else None
    module = "/".join(parts) + ".py"
    return f"{module}::{klass}::{name}" if klass else f"{module}::{name}"


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""
