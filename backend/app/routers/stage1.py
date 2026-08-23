from fastapi import APIRouter

from ..models.schemas import SearchRequest, SearchResponse

router = APIRouter(prefix="/api/v1", tags=["stage1"])

@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """Stage 1: web search agent with citation synthesis."""
    from ..services.search_service import search as run_search_pipeline
    return await run_search_pipeline(request.query, request.max_sources)
