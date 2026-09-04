import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, List

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RankedHit:
    id: str
    payload: dict
    score: float


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[0-9a-zA-Z가-힣]+", text.casefold())
    tokens = list(words)
    for word in words:
        if any("가" <= char <= "힣" for char in word) and len(word) >= 2:
            tokens.extend(f"ko:{word[index:index + 2]}" for index in range(len(word) - 1))
    return tokens


class BM25Ranker:
    def rank(self, query: str, points: List[Any], limit: int) -> List[RankedHit]:
        documents = [
            tokenize(
                f"{(point.payload or {}).get('title', '')} "
                f"{(point.payload or {}).get('content', '')}"
            )
            for point in points
        ]
        if not documents:
            return []
        query_terms = tokenize(query)
        if not query_terms:
            return []
        document_frequency = Counter()
        for tokens in documents:
            document_frequency.update(set(tokens))
        average_length = sum(len(tokens) for tokens in documents) / len(documents)
        scored = []
        k1, b = 1.5, 0.75
        for point, tokens in zip(points, documents):
            frequencies = Counter(tokens)
            score = 0.0
            for term in query_terms:
                frequency = frequencies[term]
                if not frequency:
                    continue
                frequency_docs = document_frequency[term]
                idf = math.log(1 + (len(documents) - frequency_docs + 0.5) / (frequency_docs + 0.5))
                denominator = frequency + k1 * (
                    1 - b + b * len(tokens) / max(average_length, 1)
                )
                score += idf * frequency * (k1 + 1) / denominator
            if score > 0:
                scored.append(RankedHit(str(point.id), point.payload or {}, score))
        return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]


class CrossEncoderReranker:
    def __init__(self):
        self._model = None
        self._failed = False

    def _load(self):
        if self._model is not None or self._failed:
            return self._model
        try:
            from sentence_transformers import CrossEncoder

            try:
                self._model = CrossEncoder(
                    settings.RERANKER_MODEL_NAME,
                    max_length=512,
                    device="cpu",
                    trust_remote_code=True,
                )
            except TypeError:
                self._model = CrossEncoder(
                    settings.RERANKER_MODEL_NAME,
                    max_length=512,
                    device="cpu",
                )
        except Exception as error:
            self._failed = True
            logger.warning("Cross-encoder reranker unavailable: %s", error)
        return self._model

    def rerank(self, query: str, hits: List[RankedHit], limit: int) -> List[RankedHit]:
        model = self._load()
        if not model or not hits:
            return hits[:limit]
        pairs = [
            [query, f"{hit.payload.get('title', '')}\n{hit.payload.get('content', '')}"]
            for hit in hits
        ]
        try:
            scores = model.predict(pairs, show_progress_bar=False)
            reranked = [
                RankedHit(hit.id, hit.payload, float(score))
                for hit, score in zip(hits, scores)
            ]
            return sorted(reranked, key=lambda item: item.score, reverse=True)[:limit]
        except Exception as error:
            logger.warning("Cross-encoder reranking failed: %s", error)
            return hits[:limit]


bm25_ranker = BM25Ranker()
cross_encoder_reranker = CrossEncoderReranker()
