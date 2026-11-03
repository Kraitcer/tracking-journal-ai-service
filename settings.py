"""Environment-based service configuration."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    amvera_api_key: str = ""
    amvera_base_url: str = "https://inference.waw0.amvera.ru/v1"
    amvera_model: str = ""
    tavily_api_key: str = ""
    request_timeout_seconds: float = 45.0
    max_output_tokens: int = 2000
    max_concurrent_requests: int = 3
    max_search_results: int = 5
    max_source_chars: int = 6000
    max_context_chars: int = 24000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            amvera_api_key=os.getenv("AMVERA_API_KEY", "").strip(),
            amvera_base_url=os.getenv(
                "AMVERA_BASE_URL", "https://inference.waw0.amvera.ru/v1"
            ).rstrip("/"),
            amvera_model=os.getenv("AMVERA_MODEL", "").strip(),
            tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
            request_timeout_seconds=_positive_float(
                "REQUEST_TIMEOUT_SECONDS", 45.0
            ),
            max_output_tokens=_positive_int("MAX_OUTPUT_TOKENS", 2000),
            max_concurrent_requests=_positive_int("MAX_CONCURRENT_REQUESTS", 3),
            max_search_results=_positive_int("MAX_SEARCH_RESULTS", 5),
            max_source_chars=_positive_int("MAX_SOURCE_CHARS", 6000),
            max_context_chars=_positive_int("MAX_CONTEXT_CHARS", 24000),
        )


def _positive_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value
