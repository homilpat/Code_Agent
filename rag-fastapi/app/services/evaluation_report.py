import json
from pathlib import Path


class EvaluationReportService:
    def __init__(self, result_dir: str = "/app/evaluation/results"):
        self.result_dir = Path(result_dir)

    def latest(self) -> dict:
        path = self.result_dir / "latest.json"
        if not path.exists():
            return {
                "status": "not_run",
                "message": "아직 저장된 평가 결과가 없습니다.",
            }
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            return self._dashboard_view(report)
        except (OSError, json.JSONDecodeError):
            return {
                "status": "invalid",
                "message": "평가 결과 파일을 읽을 수 없습니다.",
            }

    @staticmethod
    def _dashboard_view(report: dict) -> dict:
        def summaries(section: str) -> dict:
            profiles = report.get(section, {}).get("profiles", {})
            return {
                "profiles": {
                    name: {"summary": value.get("summary", {})}
                    for name, value in profiles.items()
                }
            }

        regression_fields = {
            "profile",
            "id",
            "query",
            "accuracy",
            "intent",
            "expected_intent",
            "question_structure",
            "expected_question_structure",
            "generation_mode",
            "expected_generation_mode",
        }
        return {
            "status": report.get("status", "invalid"),
            "created_at": report.get("created_at"),
            "dataset_version": report.get("dataset_version"),
            "dataset_cases": report.get("dataset_cases", 0),
            "retrieval": summaries("retrieval"),
            "generation": summaries("generation"),
            "regressions": [
                {key: value for key, value in item.items() if key in regression_fields}
                for item in report.get("regressions", [])
            ],
            "analysis": report.get("analysis", {}),
            "deltas": report.get("deltas", {}),
        }


evaluation_report_service = EvaluationReportService()
