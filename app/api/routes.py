"""HTTP-маршруты AI-сервиса."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.sse import event_stream
from app.schemas import AnswerRequest, AnswerResponse, EditRequest, EditResponse
from app.services.service import AIService

router = APIRouter()


def get_service(request: Request) -> AIService:
    """Возвращает общий экземпляр AI-сервиса для внедрения в обработчики запросов."""
    return request.app.state.ai_service


ServiceDependency = Annotated[AIService, Depends(get_service)]


@router.get("/", tags=["status"])
async def root() -> dict[str, str]:
    """Возвращает название сервиса и адреса документации и схемы OpenAPI."""
    return {
        "service": "Tracking Journal AI Service",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


@router.get("/health", tags=["status"])
async def health() -> dict[str, str]:
    """Подтверждает доступность приложения без проверки внешних провайдеров."""
    return {"status": "ok"}


@router.post(
    "/v1/answers",
    response_model=AnswerResponse,
    tags=["AI"],
    summary="Answer a question with optional web search and user records",
)
async def answer(
    payload: AnswerRequest, ai_service: ServiceDependency
) -> AnswerResponse:
    """Передаёт вопрос AI-сервису и возвращает готовый структурированный ответ."""
    return await ai_service.answer(payload)


@router.post(
    "/v1/edits",
    response_model=EditResponse,
    tags=["AI"],
    summary="Rewrite or continue text without changing the source",
)
async def edit(
    payload: EditRequest, ai_service: ServiceDependency
) -> EditResponse:
    """Возвращает предложенную AI-сервисом правку или продолжение исходного текста."""
    return await ai_service.edit(payload)


@router.post(
    "/v1/answers/events",
    response_class=EventSourceResponse,
    tags=["AI"],
    summary="Stream answer processing events (SSE)",
)
async def answer_events(
    payload: AnswerRequest, ai_service: ServiceDependency
) -> AsyncIterator[ServerSentEvent]:
    """Передаёт по SSE этапы подготовки ответа и итоговый результат либо ошибку."""
    async for event in event_stream(
        lambda notify: ai_service.answer(payload, notify)
    ):
        yield event


@router.post(
    "/v1/edits/events",
    response_class=EventSourceResponse,
    tags=["AI"],
    summary="Stream edit processing events (SSE)",
)
async def edit_events(
    payload: EditRequest, ai_service: ServiceDependency
) -> AsyncIterator[ServerSentEvent]:
    """Передаёт по SSE этапы правки текста и итоговый результат либо ошибку."""
    async for event in event_stream(
        lambda notify: ai_service.edit(payload, notify)
    ):
        yield event

