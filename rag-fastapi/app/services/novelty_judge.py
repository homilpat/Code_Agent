import re

from app.services.query_planner import QueryIntent, QueryPlan


class NoveltyJudge:
    """Central policy for architecture, algorithm novelty, and validation language."""

    def generation_instructions(self, plan: QueryPlan) -> str:
        if plan.intent == QueryIntent.NOVELTY_ASSESSMENT:
            return (
                "기존 구성 요소의 연결·순서·데이터 흐름 변화는 아키텍처 조합 또는 변형으로 판정하세요. "
                "손실함수·계산 연산자·학습 규칙·업데이트 절차·탐색 절차의 변화가 근거에 제시된 경우에만 알고리즘 수정으로 판정하세요. "
                "기존 방식과 비동등한 핵심 계산 규칙과 재현 가능한 절차가 모두 확인된 경우에만 '새 알고리즘 후보'라고 표현하세요. "
                "비교 실험과 반복 검증 전에는 '검증된 새 알고리즘'이라고 선언하지 마세요. "
                "영문 기술명은 근거 원문의 철자를 그대로 복사하세요. "
                "첫 문장에 가능 여부를 직접 답한 뒤, 아키텍처 제안과 알고리즘 후보를 가르는 핵심 기준을 자연스러운 문장으로 설명하세요. "
                "가능한 설계 방향은 사용자가 실제로 다음 행동을 정할 수 있을 정도로 구체적으로 최대 3개만 제안하고 중복 결론을 반복하지 마세요. "
                "고정된 섹션 제목이나 근거 번호별 요약은 사용하지 마세요."
            )
        if plan.intent == QueryIntent.DESIGN_PROPOSAL:
            return (
                "설계 제안은 참고 원문에 직접 등장한 구성 요소의 조합·변형으로만 제한하세요. "
                "원문에 없는 성능 향상이나 성공을 단정하지 말고 검증 조건을 함께 제시하세요. "
                "구성 요소를 새롭게 조합하는 것은 새로운 아키텍처 제안이고, 계산·손실함수·학습·업데이트·탐색 규칙을 새로 정의한 경우에만 새 알고리즘 후보가 될 수 있다는 경계를 설명하세요. "
                "첫 문장은 '가능합니다' 또는 '현재 근거만으로는 어렵습니다'처럼 질문에 바로 답하고, '[근거 N]에서는' 같은 문장으로 시작하지 마세요."
            )
        return ""

    def verification_instructions(self, plan: QueryPlan) -> str:
        if not plan.requires_design_judgment:
            return ""
        return (
            "참고 원문에 이름이 없는 알고리즘·학습법·평가지표·도구는 삭제하세요. "
            "모듈 조합을 새 알고리즘이라고 부르지 말고, 계산·학습·업데이트 규칙의 변화가 근거에 없으면 아키텍처 제안으로 낮춰 표현하세요. "
            "설계안의 신규성·성능·유효성은 실험 전에는 확정하지 마세요. "
            "영문 기술명은 참고 원문의 철자를 그대로 유지하세요. "
            "최종 답변은 가능 여부를 첫 문장에 직접 제시하고, 근거를 번호순으로 낭독하지 말고 하나의 설명으로 종합하세요. "
            "특히 '[근거 1]에서는', '[근거 2]와 [근거 3]은' 같은 표현은 쓰지 말고, 설명을 먼저 쓴 뒤 인용을 문장 끝에 배치하세요. "
            "구성 요소의 조합은 아키텍처 제안이며 계산·손실함수·학습·업데이트·탐색 규칙의 변화가 있을 때만 새 알고리즘 후보라는 판정 기준을 빠뜨리지 마세요. "
            "고정된 보고서형 제목은 사용하지 말고 가능한 설계 방향은 최대 3개로 제한하세요. "
            "검증 한계는 답변 마지막에 필요할 때만 한 문장으로 밝히고 같은 결론을 반복하지 마세요."
        )

    def finalize(self, answer: str, plan: QueryPlan) -> str:
        cleaned = re.sub(
            r"(?m)^\s*(?:#+\s*)?(?:직접 답변|근거 기반 설명|가능한 설계 방향|기술적 가능성|검증 필요)\s*:\s*",
            "",
            answer,
        ).strip()

        paragraphs = re.split(r"\n\s*\n", cleaned)
        unique_paragraphs = []
        seen = set()
        for paragraph in paragraphs:
            normalized = re.sub(r"[^0-9A-Za-z가-힣]+", "", paragraph).lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_paragraphs.append(paragraph.strip())
        return "\n\n".join(unique_paragraphs)


novelty_judge = NoveltyJudge()
