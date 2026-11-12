"""Обработчики ошибок HTTP API."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.service import ServiceError


def register_exception_handlers(application: FastAPI) -> None:
    """Регистрирует единый формат ответов для ошибок сервиса и проверки запросов."""

    @application.exception_handler(ServiceError)
    async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
        """Преобразует ошибку AI-сервиса в JSON с её HTTP-статусом, кодом и сообщением."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.as_dict()},
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Возвращает HTTP 422 с описаниями ошибок проверки входных данных."""
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
