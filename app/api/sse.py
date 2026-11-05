"""Потоковая передача этапов выполнения AI-операций по SSE."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastapi.sse import ServerSentEvent

from app.schemas import AnswerResponse, EditResponse
from app.services.service import ServiceError

logger = logging.getLogger("tracking_journal_ai")

ProgressCallback = Callable[[str], Awaitable[None]]
Operation = Callable[[ProgressCallback], Awaitable[AnswerResponse | EditResponse]]


async def event_stream(operation: Operation) -> AsyncIterator[ServerSentEvent]:
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
