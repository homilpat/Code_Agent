import json
import logging
import re
from enum import Enum
from typing import Any, List, Optional, Sequence

from pydantic import BaseModel, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)


class QueryIntent(str, Enum):
    GENERAL_CHAT = "GENERAL_CHAT"
    FACT_LOOKUP = "FACT_LOOKUP"
    COMPARISON = "COMPARISON"
    CAUSE_ANALYSIS = "CAUSE_ANALYSIS"
    TROUBLESHOOTING = "TROUBLESHOOTING"
    DESIGN_PROPOSAL = "DESIGN_PROPOSAL"
    NOVELTY_ASSESSMENT = "NOVELTY_ASSESSMENT"
    VALIDATION_PLAN = "VALIDATION_PLAN"


class QuestionStructure(str, Enum):
    DIRECT_LOOKUP = "DIRECT_LOOKUP"
    COMPARATIVE = "COMPARATIVE"
    CAUSAL = "CAUSAL"
    PROCEDURAL = "PROCEDURAL"
    SYNTHESIS = "SYNTHESIS"
    JUDGMENT = "JUDGMENT"
    CONVERSATIONAL = "CONVERSATIONAL"


class SubQuestion(BaseModel):
    intent: QueryIntent
    query: str = Field(min_length=1, max_length=300)


class Ambiguity(BaseModel):
    ambiguous_text: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=300)
    question_to_user: str = Field(min_length=1, max_length=300)


class PlannerOutput(BaseModel):
    primary_intent: QueryIntent
    user_goal: str = Field(min_length=1, max_length=500)
    resolved_query: str = Field(min_length=1, max_length=500)
    entities: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    sub_questions: List[SubQuestion] = Field(default_factory=list)
    requested_tasks: List[str] = Field(default_factory=list)
    question_structure: QuestionStructure = QuestionStructure.DIRECT_LOOKUP
    requires_synthesis: bool = False
    requires_judgment: bool = False
    evidence_aspects: List[str] = Field(default_factory=list)
    needs_retrieval: bool = True
    needs_comparison: bool = False
    needs_clarification: bool = False
    ambiguities: List[Ambiguity] = Field(default_factory=list)
    clarification_question: Optional[str] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def normalize_clarification(self):
        if self.ambiguities:
            self.needs_clarification = True
        if self.needs_clarification and not self.ambiguities:
            raise ValueError(
                "needs_clarification requires at least one ambiguity item"
            )
        if self.needs_clarification and not self.clarification_question:
            self.clarification_question = self.ambiguities[0].question_to_user
        if self.clarification_question and re.search(
            r"needs_clarification|ambiguities|ambiguous_text|question_to_user|"
            r"resolved_query|entity|intent|JSON|변수명|필드값?",
            self.clarification_question,
            re.IGNORECASE,
        ):
            raise ValueError("clarification question exposes an internal schema term")
        return self


class QueryPlan(BaseModel):
    original_query: str
    resolved_query: str
    search_query: str
    intent: QueryIntent
    user_goal: str
    entities: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    sub_questions: List[SubQuestion] = Field(default_factory=list)
    requested_tasks: List[str] = Field(default_factory=list)
    question_structure: QuestionStructure = QuestionStructure.DIRECT_LOOKUP
    requires_synthesis: bool = False
    requires_judgment: bool = False
    evidence_aspects: List[str] = Field(default_factory=list)
    needs_retrieval: bool = True
    needs_comparison: bool = False
    needs_clarification: bool = False
    ambiguities: List[Ambiguity] = Field(default_factory=list)
    clarification_question: Optional[str] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    planner_mode: str = "RULE_FALLBACK"

    @property
    def requires_design_judgment(self) -> bool:
        return self.intent in {
            QueryIntent.DESIGN_PROPOSAL,
            QueryIntent.NOVELTY_ASSESSMENT,
            QueryIntent.VALIDATION_PLAN,
        }


class QueryPlanner:
    _STRUCTURE_BY_INTENT = {
        QueryIntent.GENERAL_CHAT: QuestionStructure.CONVERSATIONAL,
        QueryIntent.FACT_LOOKUP: QuestionStructure.DIRECT_LOOKUP,
        QueryIntent.COMPARISON: QuestionStructure.COMPARATIVE,
        QueryIntent.CAUSE_ANALYSIS: QuestionStructure.CAUSAL,
        QueryIntent.TROUBLESHOOTING: QuestionStructure.PROCEDURAL,
        QueryIntent.DESIGN_PROPOSAL: QuestionStructure.SYNTHESIS,
        QueryIntent.NOVELTY_ASSESSMENT: QuestionStructure.JUDGMENT,
        QueryIntent.VALIDATION_PLAN: QuestionStructure.JUDGMENT,
    }
    _GENERAL_CHAT_PATTERN = re.compile(
        r"^(?:안녕(?:하세요)?|반가워|고마워|감사(?:합니다)?|잘했어|좋아|ㅇㅇ+|오케이|"
        r"그래|괜찮아|뭐해|도와줄 수 있어)\s*[.!?~ㅋㅎ]*$",
        re.IGNORECASE,
    )
    _NOVELTY_PATTERN = re.compile(r"새로운|신규|독창|최초|특허|논문")
    _DESIGN_PATTERN = re.compile(
        r"설계|아키텍처|구조|만들|구현|조합|개선|추가|변경|수정|대체|도입"
    )
    _VALIDATION_PATTERN = re.compile(r"검증|평가|실험|어블레이션|재현")
    _TROUBLE_PATTERN = re.compile(r"오류|에러|고장|장애|알람|트러블|해결|복구")
    _COMPARE_PATTERN = re.compile(r"비교|차이|대비|어느 .*좋|장단점")
    _CAUSE_PATTERN = re.compile(r"원인|왜|이유|때문")
    _AMBIGUOUS_REFERENCE_PATTERN = re.compile(
        r"그건|그게|그걸|그것|그거|그런|이건|이게|이걸|이것|이거|저건|저게|저것|저거|"
        r"그\s*(?:방식|방법|모델|알고리즘|문제|부분|내용|결과)"
    )
    _VAGUE_SHORT_PATTERN = re.compile(r"^(?:왜|어떻게|뭐야|뭔데|어때|그래서)\??$")

    def plan(
        self,
        query: str,
        history: Optional[Sequence[Any]] = None,
        llm_client=None,
        model: Optional[str] = None,
    ) -> QueryPlan:
        normalized = re.sub(r"\s+", " ", query).strip()
        if llm_client and model:
            llm_plan = self._plan_with_llm(
                query=normalized,
                history=history or [],
                llm_client=llm_client,
                model=model,
            )
            if llm_plan:
                return llm_plan
        return self._fallback_plan(normalized)

    def _plan_with_llm(
        self,
        query: str,
        history: Sequence[Any],
        llm_client,
        model: str,
    ) -> Optional[QueryPlan]:
        history_text = self._format_history(history)
        schema_example = {
            "primary_intent": "FACT_LOOKUP",
            "user_goal": "사용자가 달성하려는 실제 목표",
            "resolved_query": "대명사와 생략된 문맥을 복원한 독립 질문",
            "entities": ["핵심 대상"],
            "constraints": ["답변 시 지켜야 할 제약"],
            "sub_questions": [
                {"intent": "FACT_LOOKUP", "query": "검색 가능한 하위 질문"}
            ],
            "requested_tasks": ["필요한 작업"],
            "question_structure": "DIRECT_LOOKUP",
            "requires_synthesis": False,
            "requires_judgment": False,
            "evidence_aspects": ["답변에 필요한 근거 관점"],
            "needs_retrieval": True,
            "needs_comparison": False,
            "needs_clarification": False,
            "ambiguities": [],
            "clarification_question": None,
            "confidence": 0.9,
        }
        allowed = ", ".join(intent.value for intent in QueryIntent)
        system_prompt = (
            "당신은 질문에 답하는 모델이 아니라 질문을 작업 계획으로 변환하는 분석기입니다. "
            "인사·감사·가벼운 대화처럼 저장 문서가 없어도 답할 수 있는 요청은 primary_intent를 GENERAL_CHAT으로, needs_retrieval을 false로 설정하세요. "
            "기술 사실, 비교, 설계, 검증처럼 저장된 지식의 확인이 유용한 요청은 needs_retrieval을 true로 유지하세요. "
            "사용자의 표면적인 키워드보다 대화 문맥과 실제 목표를 우선하세요. "
            "대명사와 생략된 대상을 최근 대화에서 복원하고, 복합 질문은 독립적으로 검색 가능한 하위 질문으로 분해하세요. "
            "질문의 추론 구조를 DIRECT_LOOKUP, COMPARATIVE, CAUSAL, PROCEDURAL, SYNTHESIS, JUDGMENT, CONVERSATIONAL 중 하나로 분류하세요. "
            "여러 근거를 관계로 연결해야 하면 requires_synthesis를, 선택·신규성·타당성을 판정해야 하면 requires_judgment를 true로 하고 필요한 근거 관점을 evidence_aspects에 기록하세요. "
            "대화 문맥으로도 복원할 수 없고 정보 부족으로 답의 방향이 크게 달라질 때만 ambiguities에 모호한 표현, 이유, 사용자에게 물을 질문을 기록하고 needs_clarification을 true로 설정하세요. "
            "확인 질문은 사용자에게 바로 보여줄 한 문장의 자연스러운 한국어로 작성하세요. JSON 키, 변수명, intent, entity, missing field 같은 내부 용어를 노출하지 마세요. "
            "가능하면 사용자가 쓴 모호한 표현을 짚고 무엇을 알려주면 되는지 구체적으로 물으세요. 단순히 '다시 질문해주세요'라고만 말하지 마세요. "
            "질문에 답하거나 사실을 새로 만들지 말고 JSON 객체 하나만 출력하세요. "
            f"intent 값은 다음 중 하나만 사용하세요: {allowed}."
        )
        user_prompt = (
            f"최근 대화:\n{history_text or '(없음)'}\n\n"
            f"현재 질문:\n{query}\n\n"
            "다음 키를 모두 포함한 JSON을 생성하세요:\n"
            + json.dumps(schema_example, ensure_ascii=False)
            + "\n모호한 부분이 있을 때 ambiguities 배열 항목 형식: "
            + json.dumps(
                {
                    "ambiguous_text": "사용자가 실제로 쓴 모호한 표현",
                    "reason": "확인이 필요한 이유",
                    "question_to_user": "사용자에게 보여줄 자연스러운 한국어 질문",
                },
                ensure_ascii=False,
            )
        )

        validation_feedback = ""
        for attempt in range(2):
            try:
                response = llm_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt + validation_feedback},
                    ],
                    temperature=0.0,
                    max_tokens=700,
                )
                raw = response.choices[0].message.content or ""
                parsed = PlannerOutput.model_validate(self._extract_json(raw))
                clarification_question = parsed.clarification_question
                if parsed.needs_clarification:
                    matching_ambiguities = [
                        item for item in parsed.ambiguities
                        if item.ambiguous_text in query
                    ]
                    if not matching_ambiguities:
                        raise ValueError(
                            "ambiguity item must quote an actual expression from the user query"
                        )
                    ambiguous_text = matching_ambiguities[0].ambiguous_text
                    if ambiguous_text not in (clarification_question or ""):
                        clarification_question = (
                            f"'{ambiguous_text}'이 어떤 기술이나 내용을 가리키는지 알려주시겠어요? "
                            "대상의 이름을 함께 적어주시면 정확히 찾아볼게요."
                        )
                resolved = re.sub(r"\s+", " ", parsed.resolved_query).strip()
                guarded_intent = self._guard_intent(query, parsed.primary_intent)
                guarded_structure = self._guard_structure(
                    guarded_intent,
                    parsed.question_structure,
                )
                is_general_chat = guarded_intent == QueryIntent.GENERAL_CHAT
                return QueryPlan(
                    original_query=query,
                    resolved_query=resolved,
                    search_query=resolved,
                    intent=guarded_intent,
                    user_goal=parsed.user_goal,
                    entities=parsed.entities[:10],
                    constraints=parsed.constraints[:10],
                    sub_questions=parsed.sub_questions[:6],
                    requested_tasks=parsed.requested_tasks[:8],
                    question_structure=guarded_structure,
                    requires_synthesis=(
                        parsed.requires_synthesis
                        or guarded_structure in {
                            QuestionStructure.COMPARATIVE,
                            QuestionStructure.CAUSAL,
                            QuestionStructure.PROCEDURAL,
                            QuestionStructure.SYNTHESIS,
                            QuestionStructure.JUDGMENT,
                        }
                    ),
                    requires_judgment=(
                        parsed.requires_judgment
                        or guarded_structure == QuestionStructure.JUDGMENT
                    ),
                    evidence_aspects=parsed.evidence_aspects[:8],
                    # The routing boundary is code-owned. The model classifies the
                    # intent, but cannot skip retrieval for a knowledge task.
                    needs_retrieval=not is_general_chat,
                    needs_comparison=(
                        parsed.needs_comparison
                        or guarded_intent == QueryIntent.COMPARISON
                    ),
                    needs_clarification=parsed.needs_clarification,
                    ambiguities=parsed.ambiguities[:5],
                    clarification_question=clarification_question,
                    confidence=parsed.confidence,
                    planner_mode="LLM",
                )
            except (ValueError, ValidationError, json.JSONDecodeError) as error:
                logger.warning("Question plan validation attempt %d failed: %s", attempt + 1, error)
                validation_feedback = (
                    "\n\n이전 출력이 스키마 검증에 실패했습니다. 설명 없이 유효한 JSON 객체만 다시 출력하세요. "
                    f"오류: {str(error)[:300]}"
                )
            except Exception as error:
                logger.warning("Question planning attempt %d failed: %s", attempt + 1, error)

        return None

    def _guard_intent(self, query: str, intent: QueryIntent) -> QueryIntent:
        """Prevent model under-classification from bypassing assurance routing."""
        has_novelty = bool(self._NOVELTY_PATTERN.search(query))
        has_design = bool(self._DESIGN_PATTERN.search(query))
        if self._VALIDATION_PATTERN.search(query) and (has_novelty or has_design):
            return QueryIntent.VALIDATION_PLAN
        if has_novelty and has_design:
            return QueryIntent.NOVELTY_ASSESSMENT
        if self._TROUBLE_PATTERN.search(query):
            return QueryIntent.TROUBLESHOOTING
        if self._COMPARE_PATTERN.search(query):
            return QueryIntent.COMPARISON
        if self._CAUSE_PATTERN.search(query):
            return QueryIntent.CAUSE_ANALYSIS
        if has_design and intent == QueryIntent.FACT_LOOKUP:
            return QueryIntent.DESIGN_PROPOSAL
        return intent

    def _guard_structure(
        self,
        intent: QueryIntent,
        inferred: QuestionStructure,
    ) -> QuestionStructure:
        expected = self._STRUCTURE_BY_INTENT[intent]
        if intent in {QueryIntent.FACT_LOOKUP, QueryIntent.GENERAL_CHAT}:
            return inferred if intent == QueryIntent.FACT_LOOKUP else expected
        return expected

    @staticmethod
    def _extract_json(raw: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise ValueError("Planner response did not contain a JSON object")
        return json.loads(match.group(0))

    @staticmethod
    def _format_history(history: Sequence[Any]) -> str:
        lines = []
        for item in list(history)[-6:]:
            role = str(getattr(item, "role", "user")).lower()
            content = re.sub(r"\s+", " ", str(getattr(item, "content", ""))).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            lines.append(f"{role}: {content[:800]}")
        return "\n".join(lines)

    def _fallback_plan(self, query: str) -> QueryPlan:
        if self._GENERAL_CHAT_PATTERN.fullmatch(query.strip()):
            return QueryPlan(
                original_query=query,
                resolved_query=query,
                search_query=query,
                intent=QueryIntent.GENERAL_CHAT,
                user_goal="일반 대화에 자연스럽게 응답",
                requested_tasks=["일반 대화 응답"],
                question_structure=QuestionStructure.CONVERSATIONAL,
                needs_retrieval=False,
                confidence=0.95,
            )
        ambiguous_match = self._AMBIGUOUS_REFERENCE_PATTERN.search(query)
        vague_short = bool(self._VAGUE_SHORT_PATTERN.fullmatch(query.strip()))
        if ambiguous_match or vague_short:
            ambiguous_text = ambiguous_match.group(0) if ambiguous_match else query
            question = (
                f"'{ambiguous_text}'이 어떤 대상을 가리키는지 확인이 필요합니다. "
                "말씀하신 기술이나 내용을 구체적인 이름으로 알려주시겠어요?"
            )
            ambiguity = Ambiguity(
                ambiguous_text=ambiguous_text,
                reason="대화 분석에 실패한 상태에서는 이 표현의 대상을 안전하게 확정할 수 없습니다.",
                question_to_user=question,
            )
            return QueryPlan(
                original_query=query,
                resolved_query=query,
                search_query=query,
                intent=QueryIntent.FACT_LOOKUP,
                user_goal=query,
                needs_retrieval=False,
                needs_clarification=True,
                ambiguities=[ambiguity],
                clarification_question=question,
                confidence=0.1,
                planner_mode="SAFE_CLARIFICATION_FALLBACK",
            )

        has_novelty = bool(self._NOVELTY_PATTERN.search(query))
        has_design = bool(self._DESIGN_PATTERN.search(query))
        if self._VALIDATION_PATTERN.search(query) and (has_novelty or has_design):
            intent = QueryIntent.VALIDATION_PLAN
            tasks = ["검증 기준 정의", "비교 실험", "재현 조건"]
        elif has_novelty and has_design:
            intent = QueryIntent.NOVELTY_ASSESSMENT
            tasks = ["가능성 판단", "신규성 범위 판정", "검증 상태 확인"]
        elif has_design:
            intent = QueryIntent.DESIGN_PROPOSAL
            tasks = ["설계 방향 제안", "근거 범위 확인", "검증 조건 제시"]
        elif self._TROUBLE_PATTERN.search(query):
            intent = QueryIntent.TROUBLESHOOTING
            tasks = ["증상 확인", "근거 기반 원인 후보", "해결 절차"]
        elif self._COMPARE_PATTERN.search(query):
            intent = QueryIntent.COMPARISON
            tasks = ["비교 기준 확인", "공통점과 차이점"]
        elif self._CAUSE_PATTERN.search(query):
            intent = QueryIntent.CAUSE_ANALYSIS
            tasks = ["직접 원인", "근거 강도 확인"]
        else:
            intent = QueryIntent.FACT_LOOKUP
            tasks = ["직접 답변", "핵심 근거"]

        return QueryPlan(
            original_query=query,
            resolved_query=query,
            search_query=query,
            intent=intent,
            user_goal=query,
            requested_tasks=tasks,
            question_structure=self._STRUCTURE_BY_INTENT[intent],
            requires_synthesis=intent in {
                QueryIntent.COMPARISON,
                QueryIntent.CAUSE_ANALYSIS,
                QueryIntent.TROUBLESHOOTING,
                QueryIntent.DESIGN_PROPOSAL,
                QueryIntent.NOVELTY_ASSESSMENT,
                QueryIntent.VALIDATION_PLAN,
            },
            requires_judgment=intent in {
                QueryIntent.NOVELTY_ASSESSMENT,
                QueryIntent.VALIDATION_PLAN,
            },
            evidence_aspects=tasks,
            planner_mode="RULE_FALLBACK",
        )


query_planner = QueryPlanner()
