import logging
import uuid
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from app.config import settings

logger = logging.getLogger(__name__)

class VectorStoreService:
    def __init__(self):
        try:
            self.client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=5.0)
            self._ensure_collection()
            logger.info('Connected to Qdrant at %s:%s', settings.QDRANT_HOST, settings.QDRANT_PORT)
        except Exception as e:
            logger.warning('Failed to connect to Qdrant (%s). Using in-memory fallback.', e)
            self.client = QdrantClient(':memory:')
            self._ensure_collection()

    def _ensure_collection(self):
        try:
            collections = [c.name for c in self.client.get_collections().collections]
            if settings.QDRANT_COLLECTION not in collections:
                self.client.create_collection(
                    collection_name=settings.QDRANT_COLLECTION,
                    vectors_config=qmodels.VectorParams(
                        size=settings.VECTOR_DIMENSION,
                        distance=qmodels.Distance.COSINE
                    ),
                )
                logger.info('Collection created with dimension %d.', settings.VECTOR_DIMENSION)
        except Exception as e:
            logger.error('Error creating collection: %s', e)

    def insert_chunks(self, vectors: List[List[float]], payloads: List[Dict[str, Any]]) -> int:
        points = [
            qmodels.PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload=pay
            )
            for vec, pay in zip(vectors, payloads)
        ]
        self.client.upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=points
        )
        return len(points)

    def delete_by_source(self, source_type: str, source_id: int) -> None:
        source_filter = qmodels.Filter(must=[
            qmodels.FieldCondition(key='source_type', match=qmodels.MatchValue(value=source_type)),
            qmodels.FieldCondition(key='source_id', match=qmodels.MatchValue(value=source_id)),
        ])
        self.client.delete(
            collection_name=settings.QDRANT_COLLECTION,
            points_selector=qmodels.FilterSelector(filter=source_filter),
            wait=True,
        )

    def search(self, query_vector: List[float], limit: int = 4, domain_filter: Optional[str] = None) -> List[Any]:
        query_filter = None
        if domain_filter and domain_filter != 'ALL':
            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(key='category_section', match=qmodels.MatchValue(value=domain_filter))
                ]
            )
        try:
            result = self.client.query_points(
                collection_name=settings.QDRANT_COLLECTION,
                query=query_vector,
                query_filter=query_filter,
                limit=limit
            )
            return result.points
        except Exception as e:
            logger.error('Search error: %s', e)
            return []

    def scroll_payloads(
        self,
        limit: int = 1000,
        domain_filter: Optional[str] = None,
    ) -> List[Any]:
        query_filter = None
        if domain_filter and domain_filter != 'ALL':
            query_filter = qmodels.Filter(
                must=[qmodels.FieldCondition(
                    key='category_section',
                    match=qmodels.MatchValue(value=domain_filter),
                )]
            )
        try:
            points, _ = self.client.scroll(
                collection_name=settings.QDRANT_COLLECTION,
                scroll_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            return points
        except Exception as e:
            logger.error('Payload scroll error: %s', e)
            return []

vector_store = VectorStoreService()
