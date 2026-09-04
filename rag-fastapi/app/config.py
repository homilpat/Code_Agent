from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Manufacturing Knowledge RAG Service (LM Studio + BGE-M3)"
    QDRANT_HOST: str
    QDRANT_PORT: int
    QDRANT_COLLECTION: str
    
    # LM Studio 로컬 LLM 설정 (Docker 내부에서 호스트 머신 접근)
    LM_STUDIO_URL: str
    LM_STUDIO_API_KEY: str
    LLM_MODEL: str
    PLANNER_MODEL: Optional[str] = None
    ANSWER_MODEL: Optional[str] = None
    
    # BGE-M3 임베딩 모델 (다국어/영어논문/한국어 특화, 1024차원)
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    RERANKER_MODEL_NAME: str = "BAAI/bge-reranker-v2-m3"
    VECTOR_DIMENSION: int = 1024
    MIN_SEARCH_SCORE: float

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
