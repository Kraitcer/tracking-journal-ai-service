"""HTTP adapters for Amvera LLM Inference and Tavily Search."""

from typing import Any

import httpx

from settings import Settings


class ProviderError(Exception):
    """Raised when an external provider cannot complete a request."""

    def __init__(self, provider: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class AmveraClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, int] | None]:
        if not self.settings.amvera_api_key or not self.settings.amvera_model:
            raise ProviderError(
                "amvera",
                "Set AMVERA_API_KEY and AMVERA_MODEL before requesting a completion.",
                503,
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
            raise ProviderError("amvera", "Amvera request timed out.", 504) from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                "amvera",
                _provider_http_message(exc.response),
                502,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError("amvera", "Could not connect to Amvera.", 502) from exc
        except ValueError as exc:
            raise ProviderError("amvera", "Amvera returned invalid JSON.", 502) from exc

        try:
            choice = data["choices"][0]["message"]
            content = choice["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(
                "amvera", "Amvera returned an unexpected completion response.", 502
            ) from exc

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
    def __init__(self, settings: Settings):
        self.settings = settings

    async def search(
        self, query: str, include_images: bool
    ) -> dict[str, Any]:
        if not self.settings.tavily_api_key:
            raise ProviderError(
                "tavily",
                "Set TAVILY_API_KEY to enable web search.",
                503,
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
            raise ProviderError("tavily", "Tavily search timed out.", 504) from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                "tavily",
                _provider_http_message(exc.response),
                502,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError("tavily", "Could not connect to Tavily.", 502) from exc
        except ValueError as exc:
            raise ProviderError("tavily", "Tavily returned invalid JSON.", 502) from exc

        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ProviderError("tavily", "Tavily returned an unexpected response.", 502)
        return data


def _provider_http_message(response: httpx.Response) -> str:
    if response.status_code in {401, 403}:
        return "The external provider rejected its configured API key."
    if response.status_code == 429:
        return "The external provider rate limit was reached."
    return f"The external provider returned HTTP {response.status_code}."
