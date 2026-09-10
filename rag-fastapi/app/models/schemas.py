from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal

class DocumentChunk(BaseModel):
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class IndexRequest(BaseModel):
    source_type: str = Field(..., description="POST or MANUAL")
    source_id: int = Field(..., description="Post ID or Document ID")
    title: str
    content: str
    category: str = Field(..., description="AI_TECH, DOMAIN_SEMI, PROJECT_LOG")
    tags: Optional[str] = None
    url: Optional[str] = None
    visibility: Literal["PUBLIC", "PRIVATE", "ORGANIZATION"] = "PUBLIC"
    owner_id: Optional[int] = None
    organization_id: Optional[int] = None
    allowed_user_ids: List[int] = Field(default_factory=list)
    allowed_roles: List[str] = Field(default_factory=list)

class IndexResponse(BaseModel):
    success: bool
    source_type: str
    source_id: int
    chunks_indexed: int
    message: str

class SourceItem(BaseModel):
    source_type: str
    source_id: int
    title: str
    category: str
    url: Optional[str] = None
    snippet: str
    score: float
    chunk_index: int = 0
    citation_number: int = 0
    publisher: Optional[str] = None
    checked_at: Optional[str] = None

class HistoryMessage(BaseModel):
    role: str
    content: str


class AccessScope(BaseModel):
    user_id: Optional[int] = None
    organization_ids: List[int] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    is_admin: bool = False

class QueryRequest(BaseModel):
    query: str
    domain_filter: Optional[str] = None
    top_k: int = 4
    history: List[HistoryMessage] = Field(default_factory=list)
    retrieval_mode: Literal["dense", "hybrid", "hybrid_rerank"] = "dense"
    generation_mode: Literal["auto", "hierarchical", "qwen_direct"] = "auto"
    access_scope: AccessScope = Field(default_factory=AccessScope)
    allow_web_search: bool = True


class TraceStep(BaseModel):
    name: str
    status: str = "completed"
    latency_ms: int = 0
    detail: Optional[str] = None

class QueryResponse(BaseModel):
    query: str
    answer: str
    sources: List[SourceItem]
    response_time_ms: int
    intent: Optional[str] = None
    coverage: Optional[str] = None
    retrieval_mode: str = "dense"
    generation_mode: str = "auto"
    selected_citation_count: int = 0
    missing_points: List[str] = Field(default_factory=list)
    trace: List[TraceStep] = Field(default_factory=list)

class CategoryCandidate(BaseModel):
    id: int
    name: str
    section: str
    description: Optional[str] = None

class ClassifyRequest(BaseModel):
    title: str
    content: str
    categories: List[CategoryCandidate]

class ClassifyResponse(BaseModel):
    category_id: int
    category_name: str
    section: str
    confidence: float

class DraftRequest(BaseModel):
    content: str
    categories: List[CategoryCandidate]
    title: Optional[str] = None

class DraftResponse(BaseModel):
    title: str
    summary: str
    key_points: List[str]
    learning_directions: List[str]
    category_id: int
    category_name: str
    section: str
    confidence: float


class LearningDirectionRequest(BaseModel):
    post_id: int
    title: str
    content: str
    category: str
    existing_directions: List[str] = Field(default_factory=list)
    checked_direction_ids: List[str] = Field(default_factory=list)
    include_web: bool = True
    max_recommendations: int = Field(default=4, ge=1, le=6)
    access_scope: AccessScope = Field(default_factory=AccessScope)


class LearningSource(BaseModel):
    citation_number: int
    source_type: Literal["INTERNAL", "WEB"]
    source_id: Optional[int] = None
    title: str
    url: str
    publisher: str
    snippet: str
    score: float = 0.0
    checked_at: Optional[str] = None


class LearningRecommendation(BaseModel):
    id: str
    topic: str
    reason: str
    evidence_status: Literal["INTERNAL", "WEB", "IDEA"]
    citation_numbers: List[int] = Field(default_factory=list)
    checked: bool = False


class LearningDirectionResponse(BaseModel):
    post_id: int
    recommendations: List[LearningRecommendation]
    sources: List[LearningSource]
    retrieval_mode: str = "hybrid_rerank"
    web_search_used: bool = False
    response_time_ms: int
    trace: List[TraceStep] = Field(default_factory=list)
