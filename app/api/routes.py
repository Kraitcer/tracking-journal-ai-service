"""HTTP-маршруты AI-сервиса и потоковая передача событий."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.schemas import AnswerRequest, AnswerResponse, EditRequest, EditResponse
from app.services.service import AIService, ServiceError

logger = logging.getLogger("tracking_journal_ai")

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
    async for event in _event_stream(
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
    async for event in _event_stream(
        lambda notify: ai_service.edit(payload, notify)
    ):
        yield event


ProgressCallback = Callable[[str], Awaitable[None]]
Operation = Callable[[ProgressCallback], Awaitable[AnswerResponse | EditResponse]]


async def _event_stream(operation: Operation) -> AsyncIterator[ServerSentEvent]:
    """Запускает AI-операцию и выдаёт SSE-события начала, прогресса и результата.

    Передаёт ошибки отдельными событиями, логирует неожиданные исключения
    и отменяет незавершённую операцию при закрытии потока.
    """
    request_id = str(uuid4())
    queue: asyncio.Queue[tuple[str | None, Any]] = asyncio.Queue()

    async def notify(stage: str) -> None:
        """Ставит в очередь событие прогресса с этапом и идентификатором потока."""
        await queue.put(("progress", {"request_id": request_id, "stage": stage}))

    async def run_operation() -> None:
        """Выполняет операцию и ставит в очередь результат или ошибку и признак завершения."""
        try:
            response = await operation(notify)
            await queue.put(("result", response.model_dump(mode="json")))
        except ServiceError as exc:
            await queue.put(
                (
                    "error",
                    {
                        "request_id": request_id,
                        "code": exc.code,
                        "message": exc.message,
                    },
                )
            )
        # Keep unexpected failures inside the stream and avoid exposing internal details.
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Unexpected streaming request failure: %s", request_id)
            await queue.put(
                (
                    "error",
                    {
                        "request_id": request_id,
                        "code": "internal_error",
                        "message": "The AI request failed unexpectedly.",
                    },
                )
            )
        finally:
            await queue.put((None, None))

    task = asyncio.create_task(run_operation())
    yield ServerSentEvent(
        event="started",
        data={"request_id": request_id},
    )
    try:
        while True:
            event_name, data = await queue.get()
            if event_name is None:
                break
            yield ServerSentEvent(event=event_name, data=data)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
