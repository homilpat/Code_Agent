import logging
import json

from app.models.schemas import SourceItem
from app.services.evidence_structurer import StructuredEvidence

from app.services.query_planner import QueryPlan

logger = logging.getLogger(__name__)


class AnswerRenderer:
    @staticmethod
    def _complete(llm_client, model: str, messages):
        last_error = None
        for attempt in range(2):
            try:
                return llm_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.0,
                )
            except Exception as error:
                last_error = error
                logger.warning("Draft generation attempt %d failed: %s", attempt + 1, error)
        raise last_error

    def generate_draft(
        self,
        llm_client,
        model: str,
        plan: QueryPlan,
        context_text: str,
        policy_instructions: str = "",
    ) -> str:
        style_instructions = self._style_instructions(plan)
        system_prompt = (
            "당신은 반도체 제조 공정 및 AI RAG 기술 지식 전문가 어시스턴트입니다. "
            "사용자와 대화하듯 자연스럽고 명확하게 답하세요. 첫 1~2문장에서 질문에 직접 답하고 결론을 미루지 마세요. "
            "'[근거 1]에서는', '[근거 2]와 [근거 3]은'처럼 출처 번호를 문장의 주어로 삼거나 근거를 번호순으로 해설하지 마세요. "
            "여러 원문에서 확인되는 내용을 하나의 설명으로 종합하고, 인용은 관련 문장이나 문단 끝에 자연스럽게 붙이세요. "
            "검색된 근거를 모두 언급할 의무는 없습니다. 질문에 직접 답하는 데 필요한 근거만 사용하고, 관련성이 약한 근거는 답변에서 제외하세요. "
            "원문이 직접 말하는 사실과 그 사실에서 도출한 판단·설계 제안은 구분하되, 매 문장마다 같은 단서를 반복하지 마세요. "
            "원문에 있는 사실은 단정적으로 설명할 수 있지만, 여러 근거를 연결한 결론은 필요한 경우에만 '근거를 종합하면' 또는 '추론하면'이라고 한 번 표시하세요. "
            "원문에 없는 수치·실험 결과·기술명·장단점·성공 보장을 추가하지 마세요. "
            "사실 주장이 포함된 각 문단이나 항목에는 이를 뒷받침하는 [근거 N]을 붙이고, 여러 출처가 필요하면 모두 표시하세요. "
            "'직접 답변:', '근거 기반 설명:', '검증 필요:' 같은 고정 보고서 제목은 사용자가 요구하지 않는 한 쓰지 마세요. "
            "검색 문서에 질문의 정답이 직접 적혀 있지 않다는 경고는 결론을 대신하지 말고, 정말 중요한 한계일 때 마지막에 한 번만 짧게 밝히세요. "
            "각 문단은 앞 문단에 없던 정보를 추가해야 하며, 같은 결론을 표현만 바꿔 반복하지 마세요. "
            + style_instructions
            + policy_instructions
        )
        response = self._complete(
            llm_client=llm_client,
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"질문 의도: {plan.intent.value}\n"
                        f"요청 작업: {', '.join(plan.requested_tasks)}\n\n"
                        f"참고 지식:\n{context_text}\n\n"
                        f"질문: {plan.original_query}"
                    ),
                },
            ],
        )
        return response.choices[0].message.content or ""

    def generate_conversation(self, llm_client, model: str, query: str, history) -> str:
        history_messages = [
            {"role": item.role, "content": item.content}
            for item in list(history)[-6:]
            if item.role in {"user", "assistant"} and item.content.strip()
        ]
        response = self._complete(
            llm_client=llm_client,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 Knowledge Hub의 자연스러운 한국어 어시스턴트입니다. "
                        "저장 문서 검색이 필요 없는 일반 대화에 직접 답하세요. "
                        "근거 번호를 만들지 말고, 사용자가 요구하지 않은 보고서 형식이나 장황한 배경 설명을 덧붙이지 마세요."
                    ),
                },
                *history_messages,
                {"role": "user", "content": query},
            ],
        )
        return (response.choices[0].message.content or "").strip()

    def generate_final(
        self,
        llm_client,
        model: str,
        plan: QueryPlan,
        structured: StructuredEvidence,
        sources: list[SourceItem],
        policy_instructions: str = "",
    ) -> str:
        source_context = "\n\n".join(
            f"[근거 {source.citation_number}]\n"
            f"제목: {source.title}\n"
            f"원문: {source.snippet}"
            for source in sources
        )
        structured_json = json.dumps(structured.model_dump(), ensure_ascii=False)
        system_prompt = (
            "당신은 Knowledge Hub의 최종 한국어 답변 작성자입니다. 첫 1~2문장에서 질문에 직접 답하고 배경 설명으로 결론을 미루지 마세요. "
            "근거 구조화 결과는 참고용이며 반드시 함께 제공된 원문과 직접 대조하세요. 구조화 결과가 원문보다 강하면 원문 범위로 낮춰 쓰세요. "
            "coverage가 PARTIAL이면 missing_points의 내용을 원문 밖 지식으로 채우지 말고, 확인 가능한 답을 먼저 제시한 뒤 부족한 범위를 한 번만 자연스럽게 밝히세요. "
            "required_aspects에서 SUPPORTED인 항목만 사실로 답하고 MISSING인 항목은 답을 꾸며내지 마세요. MISSING이 있으면 무엇을 판단할 수 없는지 구체적으로 밝혀야 합니다. "
            "선택된 원문을 모두 언급할 의무는 없고 질문에 필요한 내용만 사용하세요. 원문이 직접 말하는 사실과 여러 사실을 연결한 추론을 구분하세요. "
            "사실이나 기술적 판단이 있는 문단 끝에는 정확한 [근거 N]을 붙이세요. '[근거 N]에서는'처럼 근거 번호를 문장의 주어로 쓰지 마세요. "
            "고정된 보고서형 제목을 만들지 말고, 각 문단은 앞 문단에 없던 정보를 추가해야 합니다. 같은 결론을 표현만 바꿔 반복하지 마세요. "
            "answer_focus의 결론은 처음에 한 번만 답하고 뒤에서 다시 요약하지 마세요. 구조화된 claim마다 별도 문단을 만들 필요는 없으며 관련 claim은 하나의 설명으로 합치세요. "
            "답변 길이를 임의로 채우지 말고 질문을 해결하는 데 필요한 만큼만 자연스럽게 작성하세요. 원문에 없는 수치·성능·성공 가능성·기술명을 추가하지 마세요. "
            + self._style_instructions(plan)
            + policy_instructions
        )
        response = self._complete(
            llm_client=llm_client,
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"질문: {plan.original_query}\n\n"
                        f"근거 구조화 결과:\n{structured_json}\n\n"
                        f"선택된 원문:\n{source_context}"
                    ),
                },
            ],
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _style_instructions(plan: QueryPlan) -> str:
        intent = plan.intent.value
        if intent in {"DESIGN_PROPOSAL", "NOVELTY_ASSESSMENT", "VALIDATION_PLAN"}:
            return (
                "설계·신규성 질문에는 가능 여부와 판정 이유를 먼저 말하고, 이어서 사용자가 실제로 시도할 수 있는 단계나 판정 기준을 최대 3개 제시하세요. "
                "근거에 있는 사례는 가능성을 설명하는 재료로 사용하되, 사례가 존재한다는 이유만으로 사용자의 아이디어가 새 알고리즘이라고 결론내리지 마세요. "
            )
        if intent == "TROUBLESHOOTING":
            return "트러블슈팅 질문에는 가장 가능성 높은 원인부터 확인 순서와 조치 순서로 답하세요. "
        if intent == "COMPARISON":
            return "비교 질문에는 핵심 차이를 먼저 말하고, 차이가 실제 선택에 미치는 영향까지 설명하세요. "
        if intent == "CAUSE_ANALYSIS":
            return "원인 질문에는 가장 직접적인 원인을 먼저 말하고 원인과 결과의 연결을 설명하세요. "
        return "사실 질문에는 핵심 답을 짧게 제시한 뒤 필요한 배경만 덧붙이세요. "


answer_renderer = AnswerRenderer()
