from fastapi import APIRouter

from ..models.schemas import HealthResponse, DependencyStatus

router = APIRouter(tags=["health"])

@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Dependency health check."""
    import asyncio
    from ..vector_store import store as vector_store
    from ..utils.cache import _get_redis
    from ..llm_router import router as llm_router
    from ..config import settings
    import httpx

    async def _check_qdrant() -> DependencyStatus:
        try:
            await asyncio.to_thread(vector_store._client.get_collections)
            return DependencyStatus(name="qdrant", status="up", detail="connected")
        except Exception as exc:
            return DependencyStatus(name="qdrant", status="down", detail=str(exc))

    async def _http_get(url: str, headers: dict | None = None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers=headers or {})
            resp.raise_for_status()
            return resp

    async def _check_ollama() -> DependencyStatus:
        try:
            await _http_get(f"{settings.OLLAMA_ENDPOINT}/api/tags")
            return DependencyStatus(name="ollama", status="up", detail="model list OK")
        except Exception as exc:
            return DependencyStatus(name="ollama", status="down", detail=str(exc))

    async def _check_redis() -> DependencyStatus:
        client = _get_redis()
        if client is None:
            return DependencyStatus(name="redis", status="down", detail="not initialised")
        try:
            await client.ping()
            return DependencyStatus(name="redis", status="up", detail="ping OK")
        except Exception as exc:
            return DependencyStatus(name="redis", status="down", detail=str(exc))

    async def _check_nvidia_nim() -> DependencyStatus:
        from ..context import get_request_overrides
        overrides = get_request_overrides()
        api_key = (overrides.nvidia_api_key if overrides and overrides.nvidia_api_key else settings.NVIDIA_NIM_API_KEY)
        endpoint = (overrides.nvidia_endpoint if overrides and overrides.nvidia_endpoint else settings.NVIDIA_NIM_ENDPOINT)
        if not api_key:
            return DependencyStatus(name="nvidia_nim", status="down", detail="no API key")
        try:
            await _http_get(
                f"{endpoint.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            return DependencyStatus(name="nvidia_nim", status="up", detail="API reachable")
        except Exception as exc:
            return DependencyStatus(name="nvidia_nim", status="down", detail=str(exc))

    async def _check_openrouter() -> DependencyStatus:
        from ..context import get_request_overrides
        overrides = get_request_overrides()
        api_key = (overrides.openrouter_api_key if overrides and overrides.openrouter_api_key else settings.OPENROUTER_API_KEY)
        endpoint = (overrides.openrouter_endpoint if overrides and overrides.openrouter_endpoint else settings.OPENROUTER_ENDPOINT)
        if not api_key:
            return DependencyStatus(name="openrouter", status="down", detail="no API key")
        try:
            await _http_get(
                f"{endpoint.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            return DependencyStatus(name="openrouter", status="up", detail="API reachable")
        except Exception as exc:
            return DependencyStatus(name="openrouter", status="down", detail=str(exc))

    results = await asyncio.gather(
        _check_qdrant(),
        _check_ollama(),
        _check_redis(),
        _check_nvidia_nim(),
        _check_openrouter(),
    )
    down = [r for r in results if r.status == "down"]
    return HealthResponse(
        status="degraded" if down else "ok",
        dependencies=list(results),
    )
