import hashlib
import html
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import List

from app.config import settings
from app.models.schemas import (
    LearningDirectionRequest,
    LearningDirectionResponse,
    LearningRecommendation,
    LearningSource,
    TraceStep,
)
from app.services.query_planner import QueryIntent, QueryPlan
from app.services.web_search import WebSearchService, web_search_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LearningGap:
    topic: str
    reason: str
    search_query: str


class LearningRecommender:
    def __init__(self, llm_client, evidence_retriever, web_search: WebSearchService | None = None):
        self.llm_client = llm_client
        self.evidence_retriever = evidence_retriever
        self.web_search = web_search or web_search_service

    @staticmethod
    def recommendation_id(topic: str) -> str:
        normalized = re.sub(r"\s+", " ", topic.casefold()).strip()
        return "learn-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _plain_text(value: str) -> str:
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()

    def _generate_gaps(self, request: LearningDirectionRequest) -> List[LearningGap]:
        article = self._plain_text(request.content)[:10000]
        existing = "\n".join(f"- {item}" for item in request.existing_directions[:10])
        if not self.llm_client:
            return [
                LearningGap(topic=item[:160], reason="기존에 생성된 학습 방향", search_query=item[:200])
                for item in request.existing_directions[:request.max_recommendations]
                if item.strip()
            ]

        prompt = (
            "당신은 기술 학습 설계자입니다. 본문에서 이미 충분히 설명한 주제는 절대 추천하지 마세요. "
            "본문을 이해하기 위한 빠진 선행 지식, 다음 단계의 심화 개념, 직접 검증할 실습만 찾으세요. "
            "새로운 사실을 단정하지 말고, 각 추천 이유는 본문에서 확인한 학습 공백으로만 설명하세요. "
            f"최대 {request.max_recommendations}개를 중복 없이 고르세요. 검색어는 공식 문서나 논문을 찾기 좋은 구체적인 표현으로 작성하세요. "
            "설명 없이 {\"gaps\":[{\"topic\":\"...\",\"reason\":\"...\",\"search_query\":\"...\"}]} JSON만 반환하세요."
        )
        try:
            response = self.llm_client.chat.completions.create(
                model=settings.PLANNER_MODEL or settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"제목: {request.title}\n카테고리: {request.category}\n\n"
                            f"기존 학습 방향(참고용):\n{existing or '- 없음'}\n\n본문:\n{article}"
                        ),
                    },
                ],
                temperature=0.1,
            )
            raw = response.choices[0].message.content or ""
            match = re.search(r"\{[\s\S]*\}", raw)
            if not match:
                raise ValueError("gap JSON not found")
            rows = json.loads(match.group(0)).get("gaps", [])
        except Exception as error:
            logger.warning("Learning gap generation failed: %s", error)
            rows = [
                {"topic": item, "reason": "기존에 생성된 학습 방향", "search_query": item}
                for item in request.existing_directions
            ]

        gaps = []
        seen = set()
        for row in rows:
            topic = re.sub(r"\s+", " ", str(row.get("topic", ""))).strip()[:160]
            reason = re.sub(r"\s+", " ", str(row.get("reason", ""))).strip()[:400]
            search_query = re.sub(r"\s+", " ", str(row.get("search_query", ""))).strip()[:240]
            key = topic.casefold()
            if not topic or not reason or not search_query or key in seen:
                continue
            seen.add(key)
            gaps.append(LearningGap(topic, reason, search_query))
            if len(gaps) >= request.max_recommendations:
                break
        return gaps

    def recommend(self, request: LearningDirectionRequest) -> LearningDirectionResponse:
        started = time.time()
        trace = []
        stage = time.time()
        gaps = self._generate_gaps(request)
        trace.append(TraceStep(
            name="learning_gap_analysis",
            latency_ms=int((time.time() - stage) * 1000),
            detail=f"본문에 이미 설명된 주제를 제외하고 {len(gaps)}개 후보 생성",
        ))

        sources: List[LearningSource] = []
        source_numbers = {}
        recommendations = []
        web_used = False
        internal_count = 0
        web_count = 0

        def add_source(key, **values) -> int:
            if key in source_numbers:
                return source_numbers[key]
            number = len(sources) + 1
            source_numbers[key] = number
            sources.append(LearningSource(citation_number=number, **values))
            return number

        retrieval_started = time.time()
        for gap in gaps:
            plan = QueryPlan(
                original_query=gap.search_query,
                resolved_query=gap.search_query,
                search_query=gap.search_query,
                intent=QueryIntent.FACT_LOOKUP,
                user_goal=f"{gap.topic} 학습 자료 찾기",
            )
            bundle = self.evidence_retriever.retrieve(
                plan=plan,
                top_k=2,
                domain_filter=None,
                retrieval_mode="hybrid_rerank",
                access_scope=request.access_scope,
                source_types=["POST"],
                excluded_sources=[("POST", request.post_id)],
            )
            citations = []
            status = "IDEA"
            if bundle.sources:
                status = "INTERNAL"
                internal_count += 1
                for source in bundle.sources:
                    citations.append(add_source(
                        ("INTERNAL", source.source_id, source.chunk_index),
                        source_type="INTERNAL",
                        source_id=source.source_id,
                        title=source.title,
                        url=source.url or f"/posts/{source.source_id}",
                        publisher="내부 지식창고",
                        snippet=source.snippet,
                        score=source.score,
                    ))
            elif request.include_web:
                web_used = True
                web_results = self.web_search.search(gap.search_query, limit=2)
                if web_results:
                    status = "WEB"
                    web_count += 1
                    for source in web_results:
                        citations.append(add_source(
                            ("WEB", source.url),
                            source_type="WEB",
                            title=source.title,
                            url=source.url,
                            publisher=source.publisher,
                            snippet=source.snippet,
                            score=source.score,
                            checked_at=source.checked_at,
                        ))

            item_id = self.recommendation_id(gap.topic)
            recommendations.append(LearningRecommendation(
                id=item_id,
                topic=gap.topic,
                reason=gap.reason,
                evidence_status=status,
                citation_numbers=citations,
                checked=item_id in request.checked_direction_ids,
            ))

        trace.append(TraceStep(
            name="internal_first_retrieval",
            latency_ms=int((time.time() - retrieval_started) * 1000),
            detail=f"내부 연결 {internal_count}개 · 웹 보강 {web_count}개 · 아이디어 {len(gaps) - internal_count - web_count}개",
        ))
        return LearningDirectionResponse(
            post_id=request.post_id,
            recommendations=recommendations,
            sources=sources,
            web_search_used=web_used,
            response_time_ms=int((time.time() - started) * 1000),
            trace=trace,
        )
