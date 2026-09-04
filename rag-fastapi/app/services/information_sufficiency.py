import re

from app.services.query_planner import QueryIntent, QueryPlan


class InformationSufficiencyJudge:
    """Decide whether a design-oriented question is concrete enough to retrieve."""

    _ALGORITHM_CREATION_REQUEST = re.compile(
        r"알고리즘[\s\S]{0,20}(?:만들|개발|고안|설계|창안)|"
        r"(?:만들|개발|고안|설계|창안)[\s\S]{0,20}알고리즘",
        re.IGNORECASE,
    )

    _GENERIC_REQUEST_PARTS = re.compile(
        r"나는|제가|저는|내가|새로운?|신규|독창적인?|"
        r"알고리즘(?:을|를|이|가|은|는)?|아키텍처(?:를|을|이|가|은|는)?|"
        r"만들(?:고\s*싶(?:어|다|은데)?|어\s*보(?:고\s*싶(?:어|다)?|자)|어줘|기)?|"
        r"개발(?:하고\s*싶(?:어|다)?|해줘|할까)?|고안(?:하고\s*싶(?:어|다)?|해줘|할까)?|"
        r"설계(?:하고\s*싶(?:어|다)?|해줘|할까)?|"
        r"괜찮(?:을까|을까요|아|나요)?|가능(?:할까|할까요|한가요|해)?|"
        r"해도\s*될까|할\s*수\s*있을까|싶어|싶다",
        re.IGNORECASE,
    )

    @classmethod
    def _specific_content(cls, query: str) -> str:
        residual = cls._GENERIC_REQUEST_PARTS.sub(" ", query)
        residual = re.sub(r"[^0-9A-Za-z가-힣]+", " ", residual)
        return re.sub(r"\s+", " ", residual).strip()

    def assess(self, plan: QueryPlan) -> QueryPlan:
        if plan.needs_clarification:
            return plan

        algorithm_creation_request = bool(
            self._ALGORITHM_CREATION_REQUEST.search(plan.original_query)
        )
        if not plan.requires_design_judgment and not algorithm_creation_request:
            return plan

        # A planner may expand a vague request with details the user never supplied.
        # For algorithm-creation requests, judge only the user's original wording so
        # hallucinated resolved-query details cannot bypass this guard.
        sufficiency_query = (
            plan.original_query if algorithm_creation_request else plan.resolved_query
        )
        specific_content = self._specific_content(sufficiency_query)
        compact_content = specific_content.replace(" ", "")

        if plan.intent in {QueryIntent.NOVELTY_ASSESSMENT, QueryIntent.VALIDATION_PLAN} or algorithm_creation_request:
            sufficient = len(compact_content) >= 8
            question = (
                "어떤 문제를 해결하려는지와 기존 방식에서 새로 바꾸려는 "
                "계산·학습·업데이트 규칙을 알려주시겠어요?"
            )
            reason = "신규성이나 검증 가능성을 판단할 구체적인 문제와 변경 규칙이 없습니다."
        else:
            sufficient = len(compact_content) >= 5
            question = (
                "어떤 문제를 해결하려는지와 반드시 지켜야 할 조건을 알려주시겠어요?"
            )
            reason = "설계 방향을 정하는 데 필요한 문제나 제약 조건이 없습니다."

        if sufficient:
            return plan

        return plan.model_copy(
            update={
                "needs_retrieval": False,
                "needs_clarification": True,
                "clarification_question": question,
                "confidence": min(plan.confidence, 0.4),
                "planner_mode": f"{plan.planner_mode}+SUFFICIENCY_GUARD",
            }
        )


information_sufficiency_judge = InformationSufficiencyJudge()
