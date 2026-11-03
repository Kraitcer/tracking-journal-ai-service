"""FastAPI entry point for the Tracking Journal AI service."""

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from schemas import AnswerRequest, AnswerResponse, EditRequest, EditResponse
from service import AIService, ServiceError
from settings import Settings

logger = logging.getLogger("tracking_journal_ai")


def get_service(request: Request) -> AIService:
    return request.app.state.ai_service


ServiceDependency = Annotated[AIService, Depends(get_service)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    application = FastAPI(
        title="Tracking Journal AI Service",
        description=(
            "Standalone AI API for answering questions, researching the web, "
            "using supplied records, and editing text."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.ai_service = AIService(settings or Settings.from_env())

    @application.middleware("http")
    async def limit_request_body(request: Request, call_next: Callable) -> Any:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                body_size = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "code": "invalid_content_length",
                            "message": "Content-Length must be an integer.",
                        }
                    },
                )
            if body_size > 1_000_000:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "request_too_large",
                            "message": "Request body must not exceed 1 MB.",
                        }
                    },
                )
        return await call_next(request)

    @application.exception_handler(ServiceError)
    async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Request validation failed.",
                    "details": [
                        {
                            "loc": error.get("loc", ()),
                            "msg": error.get("msg", "Invalid value."),
                            "type": error.get("type", "validation_error"),
                        }
                        for error in exc.errors()
                    ],
                }
            },
        )

    @application.get("/", tags=["status"])
    async def root() -> dict[str, str]:
        return {
            "service": "Tracking Journal AI Service",
            "docs": "/docs",
            "openapi": "/openapi.json",
        }

    @application.get("/health", tags=["status"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post(
        "/v1/answers",
        response_model=AnswerResponse,
        tags=["AI"],
        summary="Answer a question with optional web search and user records",
    )
    async def answer(
        payload: AnswerRequest, ai_service: ServiceDependency
    ) -> AnswerResponse:
        return await ai_service.answer(payload)

    @application.post(
        "/v1/edits",
        response_model=EditResponse,
        tags=["AI"],
        summary="Rewrite or continue text without changing the source",
    )
    async def edit(
        payload: EditRequest, ai_service: ServiceDependency
    ) -> EditResponse:
        return await ai_service.edit(payload)

    @application.post(
        "/v1/answers/events",
        response_class=EventSourceResponse,
        tags=["AI"],
        summary="Stream answer processing events (SSE)",
    )
    async def answer_events(
        payload: AnswerRequest, ai_service: ServiceDependency
    ) -> AsyncIterator[ServerSentEvent]:
        async for event in _event_stream(
            lambda notify: ai_service.answer(payload, notify)
        ):
            yield event

    @application.post(
        "/v1/edits/events",
        response_class=EventSourceResponse,
        tags=["AI"],
        summary="Stream edit processing events (SSE)",
    )
    async def edit_events(
        payload: EditRequest, ai_service: ServiceDependency
    ) -> AsyncIterator[ServerSentEvent]:
        async for event in _event_stream(
            lambda notify: ai_service.edit(payload, notify)
        ):
            yield event

    return application


ProgressCallback = Callable[[str], Awaitable[None]]
Operation = Callable[[ProgressCallback], Awaitable[AnswerResponse | EditResponse]]


async def _event_stream(operation: Operation) -> AsyncIterator[ServerSentEvent]:
    request_id = str(uuid4())
    queue: asyncio.Queue[tuple[str | None, Any]] = asyncio.Queue()

    async def notify(stage: str) -> None:
        await queue.put(("progress", {"request_id": request_id, "stage": stage}))

    async def run_operation() -> None:
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
        except Exception:
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


app = create_app()
