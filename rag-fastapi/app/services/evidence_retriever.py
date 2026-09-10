import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, List, Optional

from app.models.schemas import AccessScope, SourceItem
from app.services.query_planner import QueryPlan
from app.services.retrieval_strategies import RankedHit, bm25_ranker, cross_encoder_reranker


@dataclass(frozen=True)
class EvidenceBundle:
    sources: List[SourceItem]
    context_text: str

    @property
    def has_evidence(self) -> bool:
        return bool(self.sources and self.context_text)


class EvidenceRetriever:
    def __init__(
        self,
        vector_store,
        embed_query: Callable[[str], List[float]],
        min_score: float,
        max_chunks_per_source: int = 2,
    ):
        self.vector_store = vector_store
        self.embed_query = embed_query
        self.min_score = min_score
        self.max_chunks_per_source = max_chunks_per_source

    def retrieve(
        self,
        plan: QueryPlan,
        top_k: int,
        domain_filter: Optional[str],
        retrieval_mode: str = "dense",
        access_scope: Optional[AccessScope] = None,
        source_types: Optional[List[str]] = None,
        excluded_sources: Optional[List[tuple[str, int]]] = None,
    ) -> EvidenceBundle:
        query_vector = self.embed_query(plan.search_query)
        candidate_limit = max(top_k * 6, 24)
        rerank_limit = max(top_k * 3, 12)
        dense_hits = self.vector_store.search(
            query_vector=query_vector,
            limit=candidate_limit,
            domain_filter=domain_filter,
            access_scope=access_scope,
            source_types=source_types,
            excluded_sources=excluded_sources,
        )
        # MIN_SEARCH_SCORE is a cosine-similarity threshold. Apply it only to
        # dense scores; RRF and cross-encoder scores use different scales.
        dense_hits = [hit for hit in dense_hits if hit.score >= self.min_score]
        if retrieval_mode == "dense":
            hits = dense_hits
        else:
            points = self.vector_store.scroll_payloads(
                limit=1000,
                domain_filter=domain_filter,
                access_scope=access_scope,
                source_types=source_types,
                excluded_sources=excluded_sources,
            )
            lexical_hits = bm25_ranker.rank(plan.search_query, points, candidate_limit)
            hits = self._reciprocal_rank_fusion(dense_hits, lexical_hits, candidate_limit)
            if retrieval_mode == "hybrid_rerank":
                hits = cross_encoder_reranker.rerank(
                    plan.search_query,
                    hits,
                    rerank_limit,
                )
            hits = self._normalize_scores(hits)

        selected = []
        per_source_count = defaultdict(int)
        seen_content = set()

        for hit in hits:
            payload = hit.payload or {}
            source_key = (
                str(payload.get("source_type", "POST")),
                int(payload.get("source_id", 0)),
            )
            normalized_content = re.sub(
                r"\s+", " ", str(payload.get("content", "")).strip().lower()
            )
            if not normalized_content or normalized_content in seen_content:
                continue
            if per_source_count[source_key] >= self.max_chunks_per_source:
                continue

            selected.append(hit)
            seen_content.add(normalized_content)
            per_source_count[source_key] += 1
            if len(selected) >= top_k:
                break

        sources: List[SourceItem] = []
        context_chunks: List[str] = []
        for citation_number, hit in enumerate(selected, start=1):
            payload = hit.payload or {}
            content = str(payload.get("content", "")).strip()
            sources.append(SourceItem(
                source_type=payload.get("source_type", "POST"),
                source_id=payload.get("source_id", 0),
                title=payload.get("title", "Unknown"),
                category=payload.get("category_section", "ALL"),
                url=payload.get("url"),
                snippet=content,
                score=round(hit.score, 4),
                chunk_index=int(payload.get("chunk_index", 0)),
                citation_number=citation_number,
            ))
            context_chunks.append(
                f"[근거 {citation_number}]\n"
                f"제목: {payload.get('title')}\n"
                f"링크: {payload.get('url') or ''}\n"
                f"원문: {content}"
            )

        return EvidenceBundle(
            sources=sources,
            context_text="\n\n".join(context_chunks),
        )

    @staticmethod
    def _reciprocal_rank_fusion(dense_hits, lexical_hits, limit: int):
        fused = {}
        for result_list in (dense_hits, lexical_hits):
            for rank, hit in enumerate(result_list, start=1):
                key = str(hit.id)
                payload = hit.payload or {}
                if key not in fused:
                    fused[key] = RankedHit(key, payload, 0.0)
                fused[key].score += 1.0 / (60 + rank)
        return sorted(fused.values(), key=lambda item: item.score, reverse=True)[:limit]

    @staticmethod
    def _normalize_scores(hits):
        """Expose non-cosine rankings on a stable 0..1 display scale."""
        if not hits:
            return []
        low = min(hit.score for hit in hits)
        high = max(hit.score for hit in hits)
        if high == low:
            return [RankedHit(hit.id, hit.payload, 1.0) for hit in hits]
        return [
            RankedHit(hit.id, hit.payload, (hit.score - low) / (high - low))
            for hit in hits
        ]
