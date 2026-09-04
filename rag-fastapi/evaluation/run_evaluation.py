#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import re
import statistics
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT / "golden_dataset.json"
DEFAULT_RESULTS = ROOT / "results"


def post_json(url: str, payload: dict, timeout: int = 600) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def contains_group(answer: str, alternatives: list[str]) -> bool:
    normalized = re.sub(r"\s+", "", answer).casefold()
    return any(re.sub(r"\s+", "", term).casefold() in normalized for term in alternatives)


def source_metrics(expected_ids: list[int], sources: list[dict]) -> dict:
    actual = [int(source.get("source_id", 0)) for source in sources]
    if not expected_ids:
        return {
            "hit_at_k": 1.0 if not actual else 0.0,
            "recall_at_k": 1.0 if not actual else 0.0,
            "mrr": 1.0 if not actual else 0.0,
        }
    expected = set(expected_ids)
    matched = expected.intersection(actual)
    first_rank = next((index for index, item in enumerate(actual, 1) if item in expected), None)
    return {
        "hit_at_k": 1.0 if matched else 0.0,
        "recall_at_k": len(matched) / len(expected),
        "mrr": 1.0 / first_rank if first_rank else 0.0,
    }


def grounded_block_ratio(answer: str) -> float:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", answer) if block.strip()]
    if not blocks:
        return 0.0
    safe_limit = re.compile(r"근거.{0,16}(?:부족|없)|확인.{0,16}(?:어렵|없)|답하기 어렵")
    grounded = sum(
        1 for block in blocks
        if re.search(r"\[근거\s+\d+\]", block) or safe_limit.search(block)
    )
    return grounded / len(blocks)


def score_generation(case: dict, response: dict) -> dict:
    answer = response.get("answer", "")
    sources = response.get("sources", [])
    expected_behavior = case["expected_behavior"]
    coverage = response.get("coverage")
    term_groups = case.get("required_terms", [])
    term_score = (
        sum(contains_group(answer, group) for group in term_groups) / len(term_groups)
        if term_groups else 1.0
    )
    retrieval = source_metrics(case.get("expected_source_ids", []), sources)
    citation_numbers = [int(value) for value in re.findall(r"\[근거\s+(\d+)\]", answer)]
    valid_numbers = {int(source.get("citation_number", 0)) for source in sources}
    citation_validity = 1.0 if all(number in valid_numbers for number in citation_numbers) else 0.0
    if expected_behavior == "CLARIFY":
        behavior_ok = coverage == "NEEDS_CLARIFICATION"
    elif expected_behavior == "CHAT":
        behavior_ok = response.get("intent") == "GENERAL_CHAT" and not sources
    elif expected_behavior == "NO_EVIDENCE":
        behavior_ok = not sources and coverage in {"NO_EVIDENCE", "PARTIAL"}
    elif expected_behavior == "PARTIAL":
        behavior_ok = coverage == "PARTIAL"
    else:
        behavior_ok = bool(answer and sources)
    accuracy = 0.4 * float(behavior_ok) + 0.3 * term_score + 0.3 * retrieval["hit_at_k"]
    return {
        "id": case["id"],
        "query": case["query"],
        "passed": accuracy >= 0.75 and citation_validity == 1.0,
        "accuracy": round(accuracy, 4),
        "term_coverage": round(term_score, 4),
        "grounded_block_ratio": round(grounded_block_ratio(answer), 4),
        "citation_validity": citation_validity,
        "behavior_correct": bool(behavior_ok),
        "retrieval": retrieval,
        "latency_ms": response.get("response_time_ms", 0),
        "intent": response.get("intent"),
        "coverage": coverage,
        "source_ids": [source.get("source_id") for source in sources],
        "answer": answer,
        "trace": response.get("trace", []),
    }


def average(rows: list[dict], key: str) -> float:
    values = [float(row[key]) for row in rows]
    return round(statistics.fmean(values), 4) if values else 0.0


def summarize_generation(rows: list[dict]) -> dict:
    return {
        "cases": len(rows),
        "pass_rate": average([{"value": float(row["passed"])} for row in rows], "value"),
        "accuracy": average(rows, "accuracy"),
        "term_coverage": average(rows, "term_coverage"),
        "grounded_block_ratio": average(rows, "grounded_block_ratio"),
        "citation_validity": average(rows, "citation_validity"),
        "latency_ms": round(statistics.fmean(row["latency_ms"] for row in rows), 1) if rows else 0,
    }


def summarize_retrieval(rows: list[dict]) -> dict:
    return {
        "cases": len(rows),
        "hit_at_k": round(statistics.fmean(row["hit_at_k"] for row in rows), 4) if rows else 0,
        "recall_at_k": round(statistics.fmean(row["recall_at_k"] for row in rows), 4) if rows else 0,
        "mrr": round(statistics.fmean(row["mrr"] for row in rows), 4) if rows else 0,
        "latency_ms": round(statistics.fmean(row["latency_ms"] for row in rows), 1) if rows else 0,
    }


def previous_deltas(previous: dict, current: dict) -> dict:
    deltas = {}
    old_profiles = previous.get("generation", {}).get("profiles", {})
    for name, profile in current.get("generation", {}).get("profiles", {}).items():
        old = old_profiles.get(name, {}).get("summary", {})
        if old:
            deltas[name] = {
                key: round(profile["summary"].get(key, 0) - old.get(key, 0), 4)
                for key in ("pass_rate", "accuracy", "grounded_block_ratio", "latency_ms")
            }
    return deltas


def latest_nonempty_profiles(results: Path, section: str, previous: dict) -> dict:
    """Resume split evaluation runs without erasing the completed half."""
    candidates = [previous]
    for path in sorted(results.glob("report-*.json"), reverse=True):
        try:
            candidates.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    for report in candidates:
        profiles = report.get(section, {}).get("profiles", {})
        if profiles and any(item.get("summary", {}).get("cases", 0) for item in profiles.values()):
            return profiles
    return {}


def markdown_report(report: dict) -> str:
    lines = [
        "# Knowledge Hub RAG Evaluation",
        "",
        f"- 실행 시각: {report['created_at']}",
        f"- Golden set: {report['dataset_cases']}문항",
        "",
        "## Retrieval",
        "",
        "| 전략 | 문항 | Hit@K | Recall@K | MRR | 평균 지연(ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, value in report["retrieval"]["profiles"].items():
        summary = value["summary"]
        lines.append(
            f"| {name} | {summary['cases']} | {summary['hit_at_k']:.3f} | "
            f"{summary['recall_at_k']:.3f} | {summary['mrr']:.3f} | {summary['latency_ms']:.1f} |"
        )
    lines.extend([
        "",
        "## Generation",
        "",
        "| 프로필 | 문항 | 통과율 | 정확성 | 근거 블록 | 인용 유효성 | 평균 지연(ms) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for name, value in report["generation"]["profiles"].items():
        summary = value["summary"]
        lines.append(
            f"| {name} | {summary['cases']} | {summary['pass_rate']:.3f} | "
            f"{summary['accuracy']:.3f} | {summary['grounded_block_ratio']:.3f} | "
            f"{summary['citation_validity']:.3f} | {summary['latency_ms']:.1f} |"
        )
    lines.extend(["", "## 실패 사례", ""])
    for item in report["regressions"][:20]:
        lines.append(f"- `{item['profile']}` / `{item['id']}`: {item['query']}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--retrieval-limit", type=int, default=50)
    parser.add_argument("--generation-limit", type=int, default=5)
    parser.add_argument(
        "--generation-profiles",
        default="qwen_direct:dense,hierarchical:dense",
    )
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    cases = dataset["cases"]
    if len(cases) != 50:
        raise ValueError(f"golden dataset must contain 50 cases, found {len(cases)}")
    args.results.mkdir(parents=True, exist_ok=True)
    latest_path = args.results / "latest.json"
    previous = {}
    if latest_path.exists():
        try:
            previous = json.loads(latest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}

    retrieval_profiles = latest_nonempty_profiles(args.results, "retrieval", previous) if args.retrieval_limit == 0 else {}
    retrieval_cases = cases[:args.retrieval_limit]
    for mode in (("dense", "hybrid", "hybrid_rerank") if args.retrieval_limit > 0 else ()):
        rows = []
        for case in retrieval_cases:
            response = post_json(
                f"{args.base_url}/api/rag/evaluation/retrieve",
                {"query": case["query"], "top_k": 4, "retrieval_mode": mode},
            )
            metrics = source_metrics(case.get("expected_source_ids", []), response.get("sources", []))
            rows.append({
                "id": case["id"],
                "query": case["query"],
                **metrics,
                "latency_ms": response.get("latency_ms", 0),
                "source_ids": [source.get("source_id") for source in response.get("sources", [])],
            })
        retrieval_profiles[mode] = {"summary": summarize_retrieval(rows), "cases": rows}

    generation_profiles = latest_nonempty_profiles(args.results, "generation", previous) if args.generation_limit == 0 else {}
    generation_cases = cases[:args.generation_limit]
    profiles_to_run = filter(None, args.generation_profiles.split(",")) if args.generation_limit > 0 else ()
    for profile in profiles_to_run:
        generation_mode, retrieval_mode = profile.split(":", 1)
        rows = []
        for case in generation_cases:
            response = post_json(
                f"{args.base_url}/api/rag/query",
                {
                    "query": case["query"],
                    "top_k": 4,
                    "retrieval_mode": retrieval_mode,
                    "generation_mode": generation_mode,
                    "history": [],
                },
            )
            rows.append(score_generation(case, response))
        generation_profiles[profile] = {"summary": summarize_generation(rows), "cases": rows}

    regressions = [
        {"profile": profile, **row}
        for profile, result in generation_profiles.items()
        for row in result["cases"]
        if not row["passed"]
    ]
    created_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    report = {
        "status": "complete",
        "created_at": created_at,
        "dataset_version": dataset["version"],
        "dataset_cases": len(cases),
        "retrieval": {"profiles": retrieval_profiles},
        "generation": {"profiles": generation_profiles},
        "regressions": regressions,
    }
    report["deltas"] = previous_deltas(previous, report) if previous else {}
    timestamp = re.sub(r"[^0-9]", "", created_at)[:14]
    (args.results / f"report-{timestamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.results / "latest.md").write_text(markdown_report(report), encoding="utf-8")
    regression_dir = ROOT / "regressions"
    regression_dir.mkdir(parents=True, exist_ok=True)
    (regression_dir / "latest_failures.json").write_text(
        json.dumps({"created_at": created_at, "cases": regressions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "report": str(latest_path),
        "retrieval": {name: value["summary"] for name, value in retrieval_profiles.items()},
        "generation": {name: value["summary"] for name, value in generation_profiles.items()},
        "regressions": len(regressions),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
