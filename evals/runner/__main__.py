"""python -m evals.runner {validate,run} -- see evals/README.md."""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from evals.runner.llm import ChatClient
from evals.runner.run import solve, validate
from evals.runner.tasks import load_tasks

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = REPO_ROOT / "evals" / "tasks"
RESULTS_DIR = REPO_ROOT / "evals" / "results"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.runner")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "run"):
        command = commands.add_parser(name)
        command.add_argument("--task", action="append", help="Task id (repeatable). Default: all.")
        command.add_argument(
            "--python",
            default=sys.executable,
            help="Interpreter that has the target project's test dependencies.",
        )
        command.add_argument("--test-timeout", type=int, default=300)
        command.add_argument("--keep", action="store_true", help="Keep workspaces for inspection.")
    run = commands.choices["run"]
    run.add_argument("--model", required=True, help="Model id as served, e.g. qwen/qwen3.6-35b-a3b")
    run.add_argument("--base-url", default="http://localhost:1234/v1")
    run.add_argument("--attempts", type=int, default=3)
    run.add_argument("--max-tokens", type=int, default=16384)
    run.add_argument("--llm-timeout", type=int, default=1800)
    args = parser.parse_args(argv)

    tasks = load_tasks(TASKS_DIR, args.task)
    if args.command == "validate":
        results = [
            validate(REPO_ROOT, task, args.python, args.test_timeout, args.keep) for task in tasks
        ]
        for result in results:
            print(f"{'VALID  ' if result['valid'] else 'INVALID'} {result['task_id']}")
            for problem in result["problems"]:
                print(f"    - {problem}")
            if result["flaky"]:
                print(f"    flaky (passed on rerun): {result['flaky']}")
        return 0 if all(result["valid"] for result in results) else 1

    client = ChatClient(
        args.base_url, args.model, max_tokens=args.max_tokens, timeout=args.llm_timeout
    )
    config = {
        "base_url": args.base_url,
        "temperature": client.temperature,
        "max_tokens": args.max_tokens,
        "attempts": args.attempts,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", args.model)
    output = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{slug}.jsonl"
    passed = 0
    with output.open("a", encoding="utf-8") as stream:
        for task in tasks:
            result = solve(
                REPO_ROOT, task, client, args.python, args.attempts, args.test_timeout, args.keep
            )
            result["config"] = config
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            stream.flush()
            passed += result["success"]
            print(
                f"{result['verdict']:<13} {task.id}  "
                f"attempts={result['attempts_used']}  {result['seconds']}s"
            )
    print(f"passed {passed}/{len(tasks)} -> {output.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
