import time
import logging
import re
import math
import json
import html
import hashlib
from typing import List, Dict
from app.config import settings
from app.models.schemas import IndexRequest, IndexResponse, QueryRequest, QueryResponse, SourceItem, TraceStep, ClassifyRequest, ClassifyResponse, DraftRequest, DraftResponse, LearningDirectionRequest, LearningDirectionResponse
from app.services.generation_router import generation_router
from app.services.answer_renderer import answer_renderer
from app.services.claim_judge import claim_judge
from app.services.evidence_retriever import EvidenceBundle, EvidenceRetriever
from app.services.evidence_structurer import evidence_structurer
from app.services.fallback_response import (
    generation_unavailable_message,
    partial_evidence_message,
)
from app.services.information_sufficiency import information_sufficiency_judge
from app.services.indexing_policy import embedding_document_text
from app.services.learning_recommender import LearningRecommender
from app.services.novelty_judge import novelty_judge
from app.services.query_planner import query_planner
from app.services.vector_store import vector_store
from app.services.web_search import web_search_service

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self):
        self._category_embedding_cache: Dict[str, List[float]] = {}
        # 1. LM Studio 로컬 LLM 클라이언트
        try:
            from openai import OpenAI
            self.llm_client = OpenAI(
                base_url=settings.LM_STUDIO_URL,
                api_key=settings.LM_STUDIO_API_KEY
            )
            logger.info("LM Studio client initialized at %s", settings.LM_STUDIO_URL)
        except Exception as e:
            self.llm_client = None
            logger.warning("LM Studio client init failed: %s", e)

        # 2. BGE-M3 임베딩 모델 (다국어/논문/기술문서)
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading BGE-M3 model (%s)...", settings.EMBEDDING_MODEL_NAME)
            self.embed_model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
            logger.info("BGE-M3 model loaded successfully.")
        except Exception as e:
            self.embed_model = None
            logger.warning("SentenceTransformer load failed (%s). Using fallback embedder.", e)

        self.evidence_retriever = EvidenceRetriever(
            vector_store=vector_store,
            embed_query=self._get_embedding,
            min_score=settings.MIN_SEARCH_SCORE,
            max_chunks_per_source=1,
        )

    def _dynamic_semantic_chunking(self, text: str, min_size: int = 60, target_size: int = 200, max_size: int = 350) -> List[str]:
        """
        [구조/의미 기반 동적 청킹 알고리즘]
        1. 마크다운 헤더(#, ##), 코드 블록(`), 문단(\n\n)을 감지하여 1차 구조적 블록으로 분할
        2. 각 블록을 문장 단위로 파싱하여 50~200자 사이의 의미가 완결된 최적 크기로 동적 결합
        3. 문맥 단절 방지를 위해 문장 단위 오버랩 자동 적용
        """
        if not text or not text.strip():
            return []

        # 1차: 마크다운 제목(#), 구분선, 빈 줄 기준으로 문단 분리
        paragraphs = re.split(r'\n\s*\n|(?:^|\n)(?=#{1,4}\s)', text)
        chunks: List[str] = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # 문단이 적정 범위(min_size ~ target_size)에 맞으면 바로 하나의 최적 청크로 채택
            if min_size <= len(para) <= max_size:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                chunks.append(para)
                continue

            # 문단이 너무 작으면 (예: 50자 미만 제목/단문) 다음 내용과 자연스럽게 결합
            if len(para) < min_size:
                if current_chunk:
                    current_chunk += "\n" + para
                else:
                    current_chunk = para
                if len(current_chunk) >= min_size:
                    chunks.append(current_chunk)
                    current_chunk = ""
                continue

            # 문단이 너무 크면 (max_size 초과) 문장 단위(마침표, 줄바꿈)로 정밀 동적 분할
            sentences = re.split(r'(?<=[.!?\n])\s+', para)
            temp_buf = ""

            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue

                if len(temp_buf) + len(sent) + 1 <= target_size:
                    temp_buf = (temp_buf + " " + sent).strip()
                else:
                    if temp_buf:
                        chunks.append(temp_buf)
                    temp_buf = sent

            if temp_buf:
                if len(temp_buf) < min_size and chunks:
                    # 너무 작으면 이전 청크 끝부분과 자연스럽게 유지
                    chunks[-1] += " " + temp_buf
                else:
                    chunks.append(temp_buf)

        if current_chunk:
            if len(current_chunk) < min_size and chunks:
                chunks[-1] += "\n" + current_chunk
            else:
                chunks.append(current_chunk)

        return [c.strip() for c in chunks if c.strip()]

    def _get_embedding(self, text: str) -> List[float]:
        if self.embed_model:
            try:
                embedding = self.embed_model.encode(text, normalize_embeddings=True)
                return embedding.tolist()
            except Exception as e:
                logger.error("BGE-M3 encode error: %s", e)
        
        # Fallback 1024-dim vector
        import hashlib
        h = int(hashlib.md5(text.encode('utf-8')).hexdigest(), 16)
        vec = [math.sin(h + i) for i in range(settings.VECTOR_DIMENSION)]
        norm = math.sqrt(sum(x*x for x in vec))
        return [x / norm for x in vec]

    def classify_post(self, req: ClassifyRequest) -> ClassifyResponse:
        if not req.categories:
            raise ValueError("분류할 카테고리가 없습니다.")

        post_text = req.title + "\n" + req.content[:4000]
        category_texts = [category.name + "\n" + (category.description or "") for category in req.categories]

        if self.embed_model:
            missing_indexes = [
                index for index, category in enumerate(req.categories)
                if category.section + "|" + category_texts[index] not in self._category_embedding_cache
            ]
            texts_to_encode = [post_text] + [category_texts[index] for index in missing_indexes]
            encoded = self.embed_model.encode(texts_to_encode, normalize_embeddings=True, batch_size=len(texts_to_encode))
            post_vector = encoded[0].tolist()
            for offset, category_index in enumerate(missing_indexes, start=1):
                cache_key = req.categories[category_index].section + "|" + category_texts[category_index]
                self._category_embedding_cache[cache_key] = encoded[offset].tolist()
            category_vectors = [
                self._category_embedding_cache[category.section + "|" + category_texts[index]]
                for index, category in enumerate(req.categories)
            ]
        else:
            post_vector = self._get_embedding(post_text)
            category_vectors = [self._get_embedding(text) for text in category_texts]

        best_category = req.categories[0]
        best_score = -1.0

        for category, category_vector in zip(req.categories, category_vectors):
            score = sum(a * b for a, b in zip(post_vector, category_vector))
            if score > best_score:
                best_score = score
                best_category = category

        return ClassifyResponse(
            category_id=best_category.id,
            category_name=best_category.name,
            section=best_category.section,
            confidence=round(max(0.0, min(1.0, best_score)), 4),
        )

    def generate_post_draft(self, req: DraftRequest) -> DraftResponse:
        plain_text = html.unescape(re.sub(r'<[^>]+>', ' ', req.content))
        plain_text = re.sub(r'\s+', ' ', plain_text).strip()
        if not plain_text:
            raise ValueError("본문에 요약할 글이 없습니다.")
        if not req.categories:
            raise ValueError("분류할 카테고리가 없습니다.")
        content_categories = [category for category in req.categories if category.section != 'PROJECT_LOG']
        if not content_categories:
            content_categories = req.categories

        first_sentence = re.split(r'(?<=[.!?。])\s+', plain_text, maxsplit=1)[0]
        fallback_title = first_sentence[:60].strip()
        if len(first_sentence) > 60:
            fallback_title = fallback_title.rstrip() + '…'
        fallback_summary = plain_text[:240].strip()
        if len(plain_text) > 240:
            fallback_summary = fallback_summary.rstrip() + '…'

        requested_title = (req.title or '').strip()
        title = requested_title or fallback_title
        summary = fallback_summary
        sentences = [item.strip() for item in re.split(r'(?<=[.!?。])\s+', plain_text) if item.strip()]
        key_points = sentences[:3] or [fallback_summary]
        learning_directions = [f'{point[:80]} 내용을 원문에서 다시 확인하기' for point in key_points[:3]]
        fallback_classification = self.classify_post(ClassifyRequest(
            title=title,
            content=plain_text,
            categories=content_categories,
        ))
        selected_category = next(
            category for category in content_categories
            if category.id == fallback_classification.category_id
        )
        category_confidence = fallback_classification.confidence
        if not self.llm_client:
            raise RuntimeError("AI 모델 클라이언트가 설정되지 않아 게시물 초안을 생성할 수 없습니다.")

        try:
            category_guide = '\n'.join(
                f'- {category.section}: {category.name} ({category.description or "설명 없음"})'
                for category in content_categories
            )
            response = self.llm_client.chat.completions.create(
                model=settings.PLANNER_MODEL or settings.LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "당신은 기술 블로그 편집자입니다. 제공된 본문에만 근거해 한국어 제목을 만들고 가장 알맞은 카테고리를 하나 선택하세요. "
                            "제목은 60자 이내로 작성하고 과장하거나 새로운 사실을 추가하지 마세요. "
                            "본문 전체의 핵심 결론을 중복 없이 2~3문장, 300자 이내의 자연스러운 한국어로 요약하세요. "
                            "본문의 목차나 첫 문장을 그대로 나열하지 말고, 본문에 없는 사실·절차·도구는 절대 추가하지 마세요. "
                            "핵심 내용 3개와 복습할 학습 방향 3개도 만드세요. "
                            "설명 없이 반드시 {\"title\":\"...\",\"summary\":\"...\",\"category_section\":\"...\","
                            "\"key_points\":[\"...\"],\"learning_directions\":[\"...\"]} JSON만 반환하세요."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f'선택 가능한 카테고리:\n{category_guide}\n\n본문:\n{plain_text[:6000]}',
                    },
                ],
                temperature=0.2,
            )
            generated = response.choices[0].message.content or ''
            json_match = re.search(r'\{[\s\S]*\}', generated)
            if not json_match:
                raise ValueError("AI 응답에서 JSON을 찾지 못했습니다.")

            parsed = json.loads(json_match.group(0))
            generated_title = str(parsed.get('title', '')).strip()
            if not requested_title:
                if not generated_title:
                    raise ValueError("AI 응답에 제목이 없습니다.")
                title = generated_title[:120]

            generated_summary = re.sub(r'\s+', ' ', str(parsed.get('summary', ''))).strip()
            if not 20 <= len(generated_summary) <= 500:
                raise ValueError("AI 응답의 요약이 없거나 허용 길이를 벗어났습니다.")
            summary = generated_summary

            generated_section = str(parsed.get('category_section', '')).strip().upper()
            llm_category = next(
                (category for category in content_categories if category.section == generated_section),
                None,
            )
            if not llm_category:
                raise ValueError("AI가 유효하지 않은 카테고리를 반환했습니다.")
            selected_category = llm_category
            category_confidence = 0.85

            generated_points = parsed.get('key_points', [])
            generated_directions = parsed.get('learning_directions', [])
            if not isinstance(generated_points, list) or not isinstance(generated_directions, list):
                raise ValueError("AI 응답의 핵심 내용 또는 학습 방향 형식이 잘못되었습니다.")
            cleaned_points = [str(item).strip()[:200] for item in generated_points if str(item).strip()]
            cleaned_directions = [str(item).strip()[:200] for item in generated_directions if str(item).strip()]
            if not cleaned_points or not cleaned_directions:
                raise ValueError("AI 응답에 핵심 내용 또는 학습 방향이 없습니다.")
            key_points = cleaned_points[:5]
            learning_directions = cleaned_directions[:5]
        except Exception as e:
            logger.error("Post draft generation failed; refusing fallback publication: %s", e)
            raise RuntimeError("AI 요약·분류 생성에 실패하여 게시물을 저장하지 않았습니다.") from e

        return DraftResponse(
            title=title,
            summary=summary,
            key_points=key_points,
            learning_directions=learning_directions,
            category_id=selected_category.id,
            category_name=selected_category.name,
            section=selected_category.section,
            confidence=category_confidence,
        )

    def index_document_or_post(self, req: IndexRequest) -> IndexResponse:
        # Re-indexing is idempotent: remove every old chunk for this source first.
        vector_store.delete_by_source(req.source_type, req.source_id)
        # [동적 최적 청킹 실행]
        chunks = self._dynamic_semantic_chunking(req.content, min_size=50, target_size=200, max_size=300)
        if not chunks:
            return IndexResponse(
                success=False,
                source_type=req.source_type,
                source_id=req.source_id,
                chunks_indexed=0,
                message="본문 내용이 비어 있습니다."
            )

        vectors = []
        payloads = []
        for i, chunk in enumerate(chunks):
            # The title carries the document's identity and often matches direct
            # definition questions more precisely than an isolated body chunk.
            vec = self._get_embedding(embedding_document_text(req.title, chunk))
            payload = {
                "source_type": req.source_type,
                "source_id": req.source_id,
                "title": req.title,
                "category_section": req.category,
                "tags": req.tags,
                "url": req.url or ('/posts/' + str(req.source_id) if req.source_type == 'POST' else None),
                "visibility": req.visibility,
                "owner_id": req.owner_id,
                "organization_id": req.organization_id,
                "allowed_user_ids": req.allowed_user_ids,
                "allowed_roles": req.allowed_roles,
                "chunk_index": i,
                "chunk_length": len(chunk),
                "content": chunk
            }
            vectors.append(vec)
            payloads.append(payload)

        indexed_count = vector_store.insert_chunks(vectors, payloads)
        return IndexResponse(
            success=True,
            source_type=req.source_type,
            source_id=req.source_id,
            chunks_indexed=indexed_count,
            message=req.title + ' 문서 (동적 최적 청크 ' + str(indexed_count) + '개 생성 완료)'
        )

    def delete_source(self, source_type: str, source_id: int) -> None:
        vector_store.delete_by_source(source_type, source_id)

    def recommend_learning_directions(
        self, req: LearningDirectionRequest
    ) -> LearningDirectionResponse:
        return LearningRecommender(
            llm_client=self.llm_client,
            evidence_retriever=self.evidence_retriever,
        ).recommend(req)

    def retrieve_for_evaluation(self, req: QueryRequest) -> dict:
        start_time = time.time()
        plan = query_planner._fallback_plan(req.query)
        if plan.needs_clarification or not plan.needs_retrieval:
            return {
                "query": req.query,
                "intent": plan.intent.value,
                "sources": [],
                "retrieval_mode": req.retrieval_mode,
                "latency_ms": int((time.time() - start_time) * 1000),
            }
        evidence = self.evidence_retriever.retrieve(
            plan=plan,
            top_k=req.top_k,
            domain_filter=req.domain_filter,
            retrieval_mode=req.retrieval_mode,
            access_scope=req.access_scope,
        )
        return {
            "query": req.query,
            "intent": plan.intent.value,
            "sources": [source.model_dump() for source in evidence.sources],
            "retrieval_mode": req.retrieval_mode,
            "latency_ms": int((time.time() - start_time) * 1000),
        }

    @staticmethod
    def _web_evidence(search_query: str, top_k: int) -> EvidenceBundle:
        web_results = web_search_service.search(search_query, limit=top_k)
        sources = []
        context_chunks = []
        for citation_number, result in enumerate(web_results, start=1):
            source_id = int(hashlib.sha256(result.url.encode("utf-8")).hexdigest()[:12], 16)
            sources.append(SourceItem(
                source_type="WEB",
                source_id=source_id,
                title=result.title,
                category="WEB",
                url=result.url,
                snippet=result.snippet,
                score=result.score,
                citation_number=citation_number,
                publisher=result.publisher,
                checked_at=result.checked_at,
            ))
            context_chunks.append(
                f"[근거 {citation_number}]\n"
                f"제목: {result.title}\n"
                f"발행처: {result.publisher}\n"
                f"확인 날짜: {result.checked_at}\n"
                f"링크: {result.url}\n"
                f"검색 결과 요약: {result.snippet}"
            )
        return EvidenceBundle(
            sources=sources,
            context_text="\n\n".join(context_chunks),
        )

    def answer_query(self, req: QueryRequest) -> QueryResponse:
        start_time = time.time()
        trace = []
        stage_start = time.time()
        plan = query_planner.plan(
            query=req.query,
            history=req.history,
            llm_client=self.llm_client,
            model=settings.PLANNER_MODEL or settings.LLM_MODEL,
        )
        trace.append(TraceStep(
            name="question_planning",
            latency_ms=int((time.time() - stage_start) * 1000),
            detail=(
                f"{plan.intent.value} / {plan.question_structure.value}; "
                f"synthesis={plan.requires_synthesis}; judgment={plan.requires_judgment}"
            ),
        ))
        stage_start = time.time()
        plan = information_sufficiency_judge.assess(plan)
        trace.append(TraceStep(
            name="information_sufficiency",
            latency_ms=int((time.time() - stage_start) * 1000),
            detail="clarification" if plan.needs_clarification else "sufficient",
        ))
        logger.info(
            "Question plan mode=%s intent=%s resolved_query=%s confidence=%.2f",
            plan.planner_mode,
            plan.intent.value,
            plan.resolved_query,
            plan.confidence,
        )
        if plan.needs_clarification:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return QueryResponse(
                query=req.query,
                answer=plan.clarification_question or "질문의 대상을 조금 더 구체적으로 알려주세요.",
                sources=[],
                response_time_ms=elapsed_ms,
                intent=plan.intent.value,
                coverage="NEEDS_CLARIFICATION",
                retrieval_mode=req.retrieval_mode,
                generation_mode=req.generation_mode,
                trace=trace,
            )
        if not plan.needs_retrieval:
            if not self.llm_client:
                answer = "지금은 대화 모델에 연결할 수 없습니다. 잠시 후 다시 시도해주세요."
            else:
                stage_start = time.time()
                answer = answer_renderer.generate_conversation(
                    self.llm_client,
                    settings.ANSWER_MODEL or settings.LLM_MODEL,
                    req.query,
                    req.history,
                )
                if not answer:
                    answer = "응답을 생성하지 못했습니다. 한 번만 다시 말씀해주시겠어요?"
                trace.append(TraceStep(
                    name="direct_generation",
                    latency_ms=int((time.time() - stage_start) * 1000),
                    detail="no retrieval",
                ))
            return QueryResponse(
                query=req.query,
                answer=answer,
                sources=[],
                response_time_ms=int((time.time() - start_time) * 1000),
                intent=plan.intent.value,
                coverage="NOT_APPLICABLE",
                retrieval_mode=req.retrieval_mode,
                generation_mode=req.generation_mode,
                trace=trace,
            )
        stage_start = time.time()
        evidence = self.evidence_retriever.retrieve(
            plan=plan,
            top_k=req.top_k,
            domain_filter=req.domain_filter,
            retrieval_mode=req.retrieval_mode,
            access_scope=req.access_scope,
        )
        trace.append(TraceStep(
            name="retrieval",
            latency_ms=int((time.time() - stage_start) * 1000),
            detail=f"{req.retrieval_mode}: {len(evidence.sources)} candidates",
        ))
        retrieval_mode = req.retrieval_mode
        web_attempted = False
        if not evidence.has_evidence and req.allow_web_search:
            web_attempted = True
            stage_start = time.time()
            evidence = self._web_evidence(plan.search_query, req.top_k)
            retrieval_mode = f"{req.retrieval_mode}+web_fallback"
            trace.append(TraceStep(
                name="web_search_fallback",
                latency_ms=int((time.time() - stage_start) * 1000),
                detail=(
                    f"self-hosted SearXNG: {len(evidence.sources)} sources"
                    if evidence.has_evidence
                    else "self-hosted SearXNG: no usable source"
                ),
            ))
        sources = evidence.sources
        using_web_sources = bool(sources) and all(
            source.source_type == "WEB" for source in sources
        )
        web_source_policy = (
            "웹 검색 근거는 검색 결과에 표시된 요약 범위만 사용하세요. 링크의 전체 내용을 읽었다고 가정하지 말고, "
            "요약에 없는 세부 수치·날짜·조건을 보완하지 마세요. 웹 정보임을 답변에서 한 번 자연스럽게 밝히세요. "
            if using_web_sources else ""
        )
        coverage = "NO_EVIDENCE" if not evidence.has_evidence else "UNASSESSED"
        missing_points = []
        generation_decision = generation_router.decide(plan, req.generation_mode)
        generation_mode = generation_decision.mode
        trace.append(TraceStep(
            name="generation_routing",
            latency_ms=0,
            detail=f"{generation_mode}: {generation_decision.reason}",
        ))

        if self.llm_client and evidence.has_evidence:
            try:
                if generation_mode == "qwen_direct":
                    stage_start = time.time()
                    candidate = answer_renderer.generate_draft(
                        llm_client=self.llm_client,
                        model=settings.PLANNER_MODEL or settings.LLM_MODEL,
                        plan=plan,
                        context_text=evidence.context_text,
                        policy_instructions=(
                            novelty_judge.generation_instructions(plan)
                            + web_source_policy
                        ),
                    )
                    valid_citations = {source.citation_number for source in sources}
                    issues = claim_judge.quality_issues(
                        candidate,
                        valid_citations,
                        source_snippets=[source.snippet for source in sources],
                    )
                    if issues:
                        answer = self._partial_evidence_answer(sources, issues)
                        coverage = "PARTIAL"
                        missing_points = issues
                    else:
                        answer = claim_judge.validate_citations(candidate, valid_citations)
                        answer = novelty_judge.finalize(answer, plan)
                        coverage = "WEB_EVIDENCE" if using_web_sources else "UNASSESSED"
                    trace.append(TraceStep(
                        name="qwen_direct_generation",
                        latency_ms=int((time.time() - stage_start) * 1000),
                        detail="; ".join(issues) if issues else "passed format checks",
                    ))
                    return QueryResponse(
                        query=req.query,
                        answer=answer,
                        sources=sources,
                        response_time_ms=int((time.time() - start_time) * 1000),
                        intent=plan.intent.value,
                        coverage=coverage,
                        retrieval_mode=retrieval_mode,
                        generation_mode=generation_mode,
                        selected_citation_count=len(sources),
                        missing_points=missing_points,
                        trace=trace,
                    )

                stage_start = time.time()
                structured = evidence_structurer.structure(
                    llm_client=self.llm_client,
                    model=settings.PLANNER_MODEL or settings.LLM_MODEL,
                    plan=plan,
                    sources=sources,
                )
                coverage = structured.coverage
                missing_points = structured.missing_points
                selected_sources = evidence_structurer.select_sources(structured, sources)
                trace.append(TraceStep(
                    name="evidence_structuring",
                    latency_ms=int((time.time() - stage_start) * 1000),
                    detail=f"{coverage}: {len(selected_sources)}/{len(sources)} selected",
                ))
                if not selected_sources:
                    answer = self._partial_evidence_answer(
                        [],
                        structured.missing_points,
                    )
                    sources = []
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    return QueryResponse(
                        query=req.query,
                        answer=answer,
                        sources=sources,
                        response_time_ms=elapsed_ms,
                        intent=plan.intent.value,
                        coverage=coverage,
                        retrieval_mode=retrieval_mode,
                        generation_mode=generation_mode,
                        selected_citation_count=0,
                        missing_points=missing_points,
                        trace=trace,
                    )
                valid_citations = {
                    source.citation_number for source in selected_sources
                }
                answer = ""
                retry_feedback = ""
                generation_stage_start = time.time()
                validation_failures = []
                for generation_attempt in range(2):
                    candidate = answer_renderer.generate_final(
                        llm_client=self.llm_client,
                        model=settings.ANSWER_MODEL or settings.LLM_MODEL,
                        plan=plan,
                        structured=structured,
                        sources=selected_sources,
                        policy_instructions=(
                            novelty_judge.generation_instructions(plan)
                            + novelty_judge.verification_instructions(plan)
                            + web_source_policy
                            + retry_feedback
                        ),
                    )
                    issues = claim_judge.quality_issues(
                        candidate,
                        valid_citations,
                        require_partial_disclosure=structured.coverage == "PARTIAL",
                        source_snippets=[source.snippet for source in selected_sources],
                    )
                    if not issues:
                        cleaned = claim_judge.validate_citations(candidate, valid_citations)
                        cleaned = novelty_judge.finalize(cleaned, plan)
                        issues = claim_judge.quality_issues(
                            cleaned,
                            valid_citations,
                            require_partial_disclosure=structured.coverage == "PARTIAL",
                            source_snippets=[source.snippet for source in selected_sources],
                        )
                        if not issues:
                            answer = cleaned
                            break
                    logger.warning(
                        "Final answer quality attempt %d failed: %s",
                        generation_attempt + 1,
                        "; ".join(issues),
                    )
                    validation_failures.extend(issues)
                    retry_feedback = (
                        " 이전 답변은 다음 검사를 통과하지 못했습니다: "
                        + "; ".join(issues)
                        + " 같은 오류 없이 답변 전체를 다시 작성하세요."
                    )
                if not answer:
                    answer = self._partial_evidence_answer(
                        selected_sources,
                        structured.missing_points,
                    )
                trace.append(TraceStep(
                    name="gemma_generation_and_validation",
                    latency_ms=int((time.time() - generation_stage_start) * 1000),
                    detail=(
                        f"fallback after {len(validation_failures)} validation issue(s)"
                        if not answer or answer.startswith("현재 근거만으로")
                        else f"passed; {len(validation_failures)} retry issue(s)"
                    ),
                ))
                sources = selected_sources
            except Exception as e:
                logger.error("LM Studio LLM Generation error: %s", e)
                answer = generation_unavailable_message(has_sources=bool(sources))
                coverage = "GENERATION_FAILED"
        else:
            if not evidence.has_evidence:
                answer = (
                    "내부 지식과 웹 검색에서 이 질문을 뒷받침할 충분한 근거를 찾지 못했습니다. "
                    "질문을 더 구체적으로 작성해주세요."
                    if web_attempted
                    else "저장된 지식에서 이 질문을 뒷받침할 충분한 근거를 찾지 못했습니다. 관련 게시글을 먼저 등록하거나 질문을 더 구체적으로 작성해주세요."
                )
            else:
                answer = generation_unavailable_message(has_sources=True)
                coverage = "GENERATION_UNAVAILABLE"

        elapsed_ms = int((time.time() - start_time) * 1000)
        return QueryResponse(
            query=req.query,
            answer=answer,
            sources=sources,
            response_time_ms=elapsed_ms,
            intent=plan.intent.value,
            coverage=coverage,
            retrieval_mode=retrieval_mode,
            generation_mode=generation_mode,
            selected_citation_count=len(sources),
            missing_points=missing_points,
            trace=trace,
        )

    @staticmethod
    def _partial_evidence_answer(sources, missing_points=None) -> str:
        return partial_evidence_message(
            has_sources=bool(sources),
            missing_points=missing_points,
        )

rag_service = RAGService()
