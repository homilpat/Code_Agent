import json
import logging
import re
from typing import List, Literal

from pydantic import BaseModel, Field, ValidationError

from app.models.schemas import SourceItem
from app.services.query_planner import QueryPlan

logger = logging.getLogger(__name__)


class StructuredClaim(BaseModel):
    claim: str = Field(min_length=1, max_length=500)
    citations: List[int] = Field(min_length=1)
    kind: Literal["FACT", "INFERENCE"] = "FACT"


class RequiredAspect(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    status: Literal["SUPPORTED", "MISSING"] = "MISSING"
    citations: List[int] = Field(default_factory=list)


class StructuredEvidence(BaseModel):
    answer_focus: str = Field(min_length=1, max_length=500)
    selected_citations: List[int] = Field(default_factory=list)
    claims: List[StructuredClaim] = Field(default_factory=list)
    required_aspects: List[RequiredAspect] = Field(default_factory=list)
    coverage: Literal["COMPLETE", "PARTIAL"] = "COMPLETE"
    missing_points: List[str] = Field(default_factory=list)


class EvidenceStructurer:
    """Use the planner model only for constrained evidence selection and extraction."""

    @staticmethod
    def _extract_json(raw: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise ValueError("Evidence structurer response did not contain JSON")
        return json.loads(match.group(0))

    @staticmethod
    def _context(sources: List[SourceItem]) -> str:
        return "\n\n".join(
            f"[근거 {source.citation_number}]\n"
            f"제목: {source.title}\n"
            f"원문: {source.snippet}"
            for source in sources
        )

    @staticmethod
    def required_aspects(plan: QueryPlan) -> dict[str, str]:
        """Return code-owned evidence requirements for each reusable intent class."""
        requirements = {
            "FACT_LOOKUP": {
                "direct_answer": "질문의 핵심 사실을 직접 뒷받침하는 근거",
            },
            "COMPARISON": {
                "first_subject": "첫 번째 비교 대상의 동일 기준상 특성",
                "second_subject": "두 번째 비교 대상의 동일 기준상 특성",
                "material_difference": "두 대상의 핵심 차이와 선택에 미치는 영향",
            },
            "CAUSE_ANALYSIS": {
                "cause": "직접적인 원인",
                "causal_link": "원인과 결과가 연결되는 과정",
            },
            "TROUBLESHOOTING": {
                "cause": "증상을 설명하는 원인 후보",
                "diagnosis": "원인을 확인하는 절차",
                "remedy": "확인 결과에 따른 조치",
            },
            "DESIGN_PROPOSAL": {
                "feasibility": "요청한 구성이 가능한지 판단할 근거",
                "components": "구성 요소와 결합 방식",
                "constraints": "적용 조건이나 한계",
            },
            "NOVELTY_ASSESSMENT": {
                "baseline_rule": "기존 방식의 계산·학습·업데이트 규칙",
                "novelty_boundary": "제안한 변경이 실질적인 알고리즘 변화인지 판단할 기준",
                "validation_status": "비교 실험과 재현을 통한 검증 상태",
            },
            "VALIDATION_PLAN": {
                "target": "검증하려는 주장이나 변경 사항",
                "baseline": "비교할 기존 방식",
                "metric": "판정에 사용할 평가 기준",
                "procedure": "재현 가능한 비교 절차",
            },
        }
        return requirements.get(plan.intent.value, requirements["FACT_LOOKUP"])

    def structure(
        self,
        llm_client,
        model: str,
        plan: QueryPlan,
        sources: List[SourceItem],
    ) -> StructuredEvidence:
        allowed = {source.citation_number for source in sources}
        required = self.required_aspects(plan)
        schema_example = {
            "answer_focus": "질문에 직접 답하기 위해 다룰 핵심",
            "selected_citations": [1],
            "claims": [
                {
                    "claim": "원문이 직접 뒷받침하는 사실",
                    "citations": [1],
                    "kind": "FACT",
                }
            ],
            "required_aspects": [
                {
                    "key": key,
                    "description": description,
                    "status": "SUPPORTED",
                    "citations": [1],
                }
                for key, description in required.items()
            ],
            "coverage": "COMPLETE",
            "missing_points": [],
        }
        prompt = (
            "당신은 답변 작성자가 아니라 RAG 근거 구조화기입니다. 질문에 직접 필요한 원문만 선택하고 JSON 객체 하나만 출력하세요. "
            "검색 결과를 모두 선택할 의무는 없습니다. 단지 주제가 비슷하다는 이유로 선택하지 말고, 실제 답변 문장을 뒷받침하는 근거만 고르세요. "
            "FACT는 원문이 직접 말하는 내용만 기록하세요. 여러 원문을 연결해 도출한 내용은 INFERENCE로 표시하고, 원문 밖의 기술 사실은 만들지 마세요. "
            "같은 결론을 표현만 바꾼 claim을 여러 개 만들지 말고, 인용과 의미가 겹치는 claim은 하나로 합치세요. "
            "비교 질문은 양쪽 대상을 동일한 비교 기준으로 확인하세요. 한쪽 정보가 원문에 없거나 질문의 일부만 답할 수 있으면 coverage를 PARTIAL로 표시하고 missing_points에 부족한 항목을 적으세요. "
            "required_aspects는 제공된 key를 하나도 빼거나 추가하지 말고 모두 판정하세요. 원문이 해당 항목에 직접 답할 때만 SUPPORTED로 표시하고 인용 번호를 넣으세요. "
            "주제만 비슷하거나 간접적으로 추측해야 하는 항목은 MISSING으로 표시하고 citations를 빈 배열로 두세요. "
            "인용 번호는 제공된 번호만 사용하세요. 완성된 사용자 답변이나 서론은 쓰지 마세요."
        )
        user_content = (
            f"질문 의도: {plan.intent.value}\n"
            f"질문: {plan.original_query}\n\n"
            f"검색 원문:\n{self._context(sources)}\n\n"
            "다음 형식으로 출력하세요:\n"
            + json.dumps(schema_example, ensure_ascii=False)
        )

        last_error = None
        for attempt in range(2):
            try:
                response = llm_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.0,
                )
                raw = response.choices[0].message.content or ""
                structured = StructuredEvidence.model_validate(self._extract_json(raw))
                selected = list(dict.fromkeys(structured.selected_citations))
                if any(number not in allowed for number in selected):
                    raise ValueError("selected_citations contains an unavailable citation")

                valid_claims = []
                for claim in structured.claims:
                    citations = list(dict.fromkeys(claim.citations))
                    if citations and all(number in selected for number in citations):
                        valid_claims.append(claim.model_copy(update={"citations": citations}))
                returned_aspects = {
                    aspect.key: aspect for aspect in structured.required_aspects
                }
                validated_aspects = []
                for key, description in required.items():
                    aspect = returned_aspects.get(key)
                    citations = list(dict.fromkeys(aspect.citations)) if aspect else []
                    supported = bool(
                        aspect
                        and aspect.status == "SUPPORTED"
                        and citations
                        and all(number in selected for number in citations)
                    )
                    validated_aspects.append(
                        RequiredAspect(
                            key=key,
                            description=description,
                            status="SUPPORTED" if supported else "MISSING",
                            citations=citations if supported else [],
                        )
                    )
                missing_descriptions = [
                    aspect.description
                    for aspect in validated_aspects
                    if aspect.status == "MISSING"
                ]
                coverage = (
                    "PARTIAL"
                    if (
                        missing_descriptions
                        or structured.missing_points
                        or structured.coverage == "PARTIAL"
                    )
                    else "COMPLETE"
                )
                missing_points = list(dict.fromkeys(
                    [*structured.missing_points, *missing_descriptions]
                ))
                return structured.model_copy(
                    update={
                        "selected_citations": selected,
                        "claims": valid_claims,
                        "required_aspects": validated_aspects,
                        "coverage": coverage,
                        "missing_points": missing_points,
                    }
                )
            except (ValueError, ValidationError, json.JSONDecodeError) as error:
                last_error = error
                logger.warning("Evidence structuring attempt %d failed: %s", attempt + 1, error)
            except Exception as error:
                last_error = error
                logger.warning("Evidence structuring attempt %d failed: %s", attempt + 1, error)

        logger.warning("Evidence structuring fallback used: %s", last_error)
        fallback_citations = [source.citation_number for source in sources[:2]]
        return StructuredEvidence(
            answer_focus=plan.user_goal,
            selected_citations=fallback_citations,
            claims=[],
            required_aspects=[
                RequiredAspect(
                    key=key,
                    description=description,
                    status="MISSING",
                )
                for key, description in self.required_aspects(plan).items()
            ],
            coverage="PARTIAL",
            missing_points=["구조화 모델이 근거 범위를 확정하지 못했습니다."],
        )

    @staticmethod
    def select_sources(
        structured: StructuredEvidence,
        sources: List[SourceItem],
    ) -> List[SourceItem]:
        selected = set(structured.selected_citations)
        return [source for source in sources if source.citation_number in selected]


evidence_structurer = EvidenceStructurer()
