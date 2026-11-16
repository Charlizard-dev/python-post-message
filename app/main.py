"""FastAPI entry point.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 4000
Docs: http://localhost:4000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.platforms import build_platforms
from app.schemas import (
    ErrorDetail,
    PostingRequest,
    PostingResponse,
    PostingSummary,
    PostStatus,
    ValidationErrorResponse,
)
from app.services.posting_service import PostingService

settings = get_settings()

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
# httpx logs full request URLs at INFO; some (Telegram, Discord) embed secrets.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One pooled client for the whole app (connection reuse, single timeout policy).
    async with httpx.AsyncClient(
        timeout=settings.http_timeout,
        headers={"User-Agent": settings.user_agent},
    ) as client:
        platforms = build_platforms(settings, client)
        app.state.posting_service = PostingService(platforms, settings)
        ready = [p.name for p in platforms if not p.missing_config()]
        logger.info("Configured platforms: %s", ", ".join(ready) or "none")
        yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Publishes a short message containing one CTA link to multiple third-party "
        "platforms (Telegraph, Mastodon, Bluesky, Telegram, Discord, GitHub Gist)."
    ),
    lifespan=lifespan,
)


def get_posting_service(request: Request) -> PostingService:
    return request.app.state.posting_service


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ()) if part != "body"]
        message = err.get("msg", "Invalid value").removeprefix("Value error, ")
        details.append(ErrorDetail(field=".".join(loc) or "body", message=message))
    body = ValidationErrorResponse(details=details)
    return JSONResponse(status_code=422, content=body.model_dump())


@app.post(
    "/posting",
    response_model=PostingResponse,
    summary="Publish a message to all configured platforms",
    responses={422: {"model": ValidationErrorResponse, "description": "Invalid message"}},
    tags=["posting"],
)
async def create_posting(
    payload: PostingRequest,
    service: PostingService = Depends(get_posting_service),
) -> PostingResponse:
    results = await service.post_everywhere(payload.message, payload.cta_url)
    succeeded = sum(r.status is PostStatus.SUCCESS for r in results)
    return PostingResponse(
        success=succeeded > 0,
        summary=PostingSummary(total=len(results), succeeded=succeeded, failed=len(results) - succeeded),
        results=results,
    )


@app.get("/health", tags=["meta"])
async def health(service: PostingService = Depends(get_posting_service)) -> dict:
    return {
        "status": "ok",
        "platforms": {p.name: not p.missing_config() for p in service.platforms},
    }
