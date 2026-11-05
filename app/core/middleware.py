"""Middleware для входящих HTTP-запросов."""

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def register_middlewares(application: FastAPI) -> None:
    """Регистрирует middleware для проверки размера HTTP-запросов."""

    @application.middleware("http")
    async def limit_request_body(request: Request, call_next: Callable) -> Any:
        """Проверяет Content-Length и отклоняет заявленный размер свыше 1 000 000 байт.

        Возвращает HTTP 400 для нецелого заголовка и HTTP 413 при превышении лимита.
        При отсутствии заголовка пропускает запрос без проверки размера тела.
        """
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
