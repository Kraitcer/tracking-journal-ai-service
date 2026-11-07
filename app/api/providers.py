"""HTTP-клиенты внешних сервисов генерации текста и веб-поиска."""

import logging
from typing import Any

import httpx

from settings import Settings

logger = logging.getLogger("tracking_journal_ai")


class ProviderError(Exception):
    """Ошибка внешнего провайдера, передаваемая сервисному слою приложения."""

    def __init__(
        self,
        provider: str,
        message: str,
        status_code: int = 502,
        *,
        code: str | None = None,
    ):
        """Сохраняет провайдера, описание ошибки и HTTP-статус для ответа API."""
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.code = f"{provider}_{code or 'error'}"
        logger.warning(
            "Provider failure: provider=%s code=%s status=%s",
            provider,
            self.code,
            status_code,
        )


class AmveraClient:
    """Клиент Amvera, генерирующий ответы модели для AI-функций приложения."""

    def __init__(self, settings: Settings):
        """Создаёт клиент с настройками API, модели и таймаута запросов."""
        self.settings = settings

    async def complete(
        self, messages: list[dict[str, str]]
    ) -> tuple[str, dict[str, int] | None]:
        """Запрашивает у модели ответ и возвращает его текст и доступную статистику токенов."""
        if not self.settings.amvera_api_key or not self.settings.amvera_model:
            raise ProviderError(
                "amvera",
                "Set AMVERA_API_KEY and AMVERA_MODEL before requesting a completion.",
                503,
                code="configuration_error",
            )
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds
            ) as client:
                response = await client.post(
                    f"{self.settings.amvera_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.amvera_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.amvera_model,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "max_tokens": self.settings.max_output_tokens,
                        "temperature": 0.2,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "amvera", "Amvera request timed out.", 504, code="timeout"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise _provider_http_error("amvera", exc.response) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                "amvera", "Could not connect to Amvera.", code="connection_error"
            ) from exc
        except ValueError as exc:
            raise ProviderError(
                "amvera", "Amvera returned invalid JSON.", code="invalid_json"
            ) from exc

        if not isinstance(data, dict):
            raise ProviderError(
                "amvera",
                "Amvera completion response must be an object.",
                code="invalid_response",
            )
        choices = data.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise ProviderError(
                "amvera",
                "Amvera completion response has no valid first choice.",
                code="invalid_response",
            )
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ProviderError(
                "amvera",
                "Amvera completion choice has no valid message object.",
                code="invalid_response",
            )
        if choice.get("finish_reason") == "length":
            raise ProviderError(
                "amvera",
                "Amvera stopped generation at the output token limit "
                f"(MAX_OUTPUT_TOKENS={self.settings.max_output_tokens}); "
                "the completion may be incomplete.",
                code="output_limit",
            )
        if "content" not in message:
            raise ProviderError(
                "amvera",
                "Amvera completion message is missing content.",
                code="invalid_response",
            )
        content = message["content"]
        if content is None or (isinstance(content, str) and not content.strip()):
            raise ProviderError(
                "amvera",
                "Amvera returned no final completion text.",
                code="empty_completion",
            )
        if not isinstance(content, str):
            raise ProviderError(
                "amvera",
                "Amvera completion content must be a string.",
                code="invalid_response",
            )

        usage = data.get("usage")
        safe_usage = None
        if isinstance(usage, dict):
            safe_usage = {
                key: value
                for key, value in usage.items()
                if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                and isinstance(value, int)
            }
        return content, safe_usage


class TavilyClient:
    """Клиент Tavily для поиска веб-источников и, при необходимости, изображений."""

    def __init__(self, settings: Settings):
        """Создаёт клиент с настройками ключа API, таймаута и числа результатов."""
        self.settings = settings

    async def search(self, query: str, include_images: bool) -> dict[str, Any]:
        """Ищет источники по запросу и возвращает ответ Tavily для сборки контекста."""
        if not self.settings.tavily_api_key:
            raise ProviderError(
                "tavily",
                "Set TAVILY_API_KEY to enable web search.",
                503,
                code="configuration_error",
            )
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds
            ) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {self.settings.tavily_api_key}"},
                    json={
                        "query": query,
                        "search_depth": "basic",
                        "max_results": self.settings.max_search_results,
                        "include_raw_content": "markdown",
                        "include_images": include_images,
                        "include_image_descriptions": include_images,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "tavily", "Tavily search timed out.", 504, code="timeout"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise _provider_http_error("tavily", exc.response) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                "tavily", "Could not connect to Tavily.", code="connection_error"
            ) from exc
        except ValueError as exc:
            raise ProviderError(
                "tavily", "Tavily returned invalid JSON.", code="invalid_json"
            ) from exc

        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ProviderError(
                "tavily",
                "Tavily returned an unexpected response.",
                code="invalid_response",
            )
        return data


def _provider_http_error(provider: str, response: httpx.Response) -> ProviderError:
    """Классифицирует HTTP-ошибку без раскрытия тела ответа провайдера."""
    errors = {
        400: (
            "invalid_request",
            "The external provider rejected the completion/search request.",
        ),
        401: (
            "authentication_error",
            "The external provider rejected its configured API key.",
        ),
        403: (
            "authorization_error",
            "The external provider denied access to the requested resource.",
        ),
        402: (
            "billing_error",
            "The external provider billing or account permission check failed.",
        ),
        429: (
            "rate_limit",
            "The external provider request or concurrency limit was reached.",
        ),
        500: (
            "gateway_error",
            "The external provider gateway encountered an internal error.",
        ),
        502: (
            "upstream_error",
            "The external provider reported an upstream provider error.",
        ),
        503: ("upstream_error", "The external provider is temporarily unavailable."),
        504: ("upstream_error", "The external provider reported an upstream timeout."),
    }
    code, message = errors.get(
        response.status_code,
        ("http_error", "The external provider returned an unexpected HTTP status."),
    )
    return ProviderError(
        provider, f"{message} (HTTP {response.status_code}).", code=code
    )
