from fastapi import APIRouter, HTTPException
from app.models.schemas import IndexRequest, IndexResponse, QueryRequest, QueryResponse, ClassifyRequest, ClassifyResponse, DraftRequest, DraftResponse
from app.services.rag_service import rag_service
from app.services.evaluation_report import evaluation_report_service

router = APIRouter(prefix='/api/rag', tags=['RAG'])

@router.post('/index', response_model=IndexResponse)
def index_data(request: IndexRequest):
    try:
        return rag_service.index_document_or_post(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post('/query', response_model=QueryResponse)
def query_rag(request: QueryRequest):
    try:
        return rag_service.answer_query(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get('/health')
def health_check():
    return {'status': 'ok', 'service': 'FastAPI RAG Engine'}


@router.post('/evaluation/retrieve')
def evaluate_retrieval(request: QueryRequest):
    try:
        return rag_service.retrieve_for_evaluation(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/evaluation/latest')
def latest_evaluation():
    return evaluation_report_service.latest()

@router.post('/classify', response_model=ClassifyResponse)
def classify_post(request: ClassifyRequest):
    try:
        return rag_service.classify_post(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post('/draft', response_model=DraftResponse)
def generate_post_draft(request: DraftRequest):
    try:
        return rag_service.generate_post_draft(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete('/source/{source_type}/{source_id}', status_code=204)
def delete_source(source_type: str, source_id: int):
    try:
        rag_service.delete_source(source_type, source_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
