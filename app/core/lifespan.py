"""Настройка жизненного цикла приложения."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Настраивает логирование при запуске приложения до начала обработки запросов."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    yield
