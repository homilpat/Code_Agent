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
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "status": "invalid",
                "message": "평가 결과 파일을 읽을 수 없습니다.",
            }


evaluation_report_service = EvaluationReportService()
