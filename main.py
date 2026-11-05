"""Точка входа AI-сервиса: сборка приложения и регистрация компонентов."""

from fastapi import FastAPI

from app.api.routes import router
from app.core.exception_handlers import register_exception_handlers
from app.core.lifespan import lifespan
from app.core.middleware import register_middlewares
from app.services.service import AIService
from settings import Settings

def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт FastAPI-приложение и подключает его основные компоненты.

    Использует переданные настройки или загружает их из окружения.
    """
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
    register_middlewares(application)
    register_exception_handlers(application)
    application.include_router(router)
    return application


app = create_app()

# app = FastAPI(
#         title="Tracking Journal AI Service",
#         description=(
#             "Standalone AI API for answering questions, researching the web, "
#             "using supplied records, and editing text."
#         ),
#         version="0.1.0",
#         lifespan=lifespan,
#     )
# app.state.ai_service = AIService(Settings.from_env())
# register_middlewares(app)
# register_exception_handlers(app)
# app.include_router(router)



