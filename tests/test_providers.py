import asyncio
import json
import logging
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.providers import (
    AiHereClient,
    AmveraClient,
    CompletionResult,
    FailoverClient,
    ProviderError,
    TavilyClient,
)
from main import create_app
from settings import Settings


@pytest.fixture
def settings():
    return Settings(
        aihere_api_key="private-aihere-key",
        aihere_model="gpt-5-6-luna",
        amvera_api_key="private-test-key",
        amvera_model="test-model",
        tavily_api_key="private-search-key",
    )


@pytest.fixture
def mock_http(monkeypatch):
    original_client = httpx.AsyncClient
    requests = []

    def install(response=None, error=None):
        def handler(request):
            requests.append(request)
            if error is not None:
                raise error
            return response

        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            "app.api.providers.httpx.AsyncClient",
            lambda **kwargs: original_client(transport=transport, **kwargs),
        )
        return requests

    return install


def complete(client, model=None):
    return asyncio.run(
        client.complete([{"role": "user", "content": "private-prompt"}], model)
    )


@pytest.mark.parametrize(
    "data,code",
    [
        (None, "invalid_response"),
        ([], "invalid_response"),
        ({}, "invalid_response"),
        ({"choices": []}, "invalid_response"),
        ({"choices": {}}, "invalid_response"),
        ({"choices": [None]}, "invalid_response"),
        ({"choices": [{}]}, "invalid_response"),
        ({"choices": [{"message": []}]}, "invalid_response"),
        ({"choices": [{"message": {}}]}, "invalid_response"),
        ({"choices": [{"message": {"content": []}}]}, "invalid_response"),
        ({"choices": [{"message": {"content": 123}}]}, "invalid_response"),
        ({"choices": [{"message": {"content": None}}]}, "empty_completion"),
        ({"choices": [{"message": {"content": ""}}]}, "empty_completion"),
        ({"choices": [{"message": {"content": " \n\t"}}]}, "empty_completion"),
    ],
)
def test_completion_response_categories(settings, mock_http, data, code):
    mock_http(httpx.Response(200, content=json.dumps(data)))

    with pytest.raises(ProviderError) as caught:
        complete(AmveraClient(settings))

    assert caught.value.code == f"amvera_{code}"
    assert caught.value.status_code == 502


@pytest.mark.parametrize(
    "data,code",
    [
        (None, "invalid_response"),
        ([], "invalid_response"),
        ({}, "empty_completion"),
        ({"content": None}, "empty_completion"),
        ({"content": ""}, "empty_completion"),
        ({"content": 123}, "invalid_response"),
    ],
)
def test_aihere_completion_response_categories(settings, mock_http, data, code):
    mock_http(httpx.Response(200, content=json.dumps(data)))

    with pytest.raises(ProviderError) as caught:
        complete(AiHereClient(settings))

    assert caught.value.code == f"aihere_{code}"
    assert caught.value.status_code == 502


def test_aihere_uses_documented_endpoint_and_normalizes_response(settings, mock_http):
    content = '{"blocks":[{"type":"paragraph","text":"Answer","citations":[]}]}'
    usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    requests = mock_http(
        httpx.Response(
            200,
            json={
                "request_id": "request-1",
                "model": "gpt-5-6-luna",
                "content": content,
                "finish_reason": "stop",
                "usage": usage,
                "cost_rub": 0.01,
            },
        )
    )

    result = complete(AiHereClient(settings))

    assert result.content == content
    assert result.usage == usage
    assert result.model == "gpt-5-6-luna"
    sent = requests[0]
    assert str(sent.url) == "https://api.aihere.ru/api/v1/chats/completions"
    assert sent.headers["authorization"] == "Bearer private-aihere-key"
    body = json.loads(sent.content)
    assert body["stream"] is False
    assert body["model"] == settings.aihere_model
    assert body["max_tokens"] == settings.max_output_tokens
    assert "response_format" not in body


def test_aihere_request_model_overrides_configured_default(settings, mock_http):
    requests = mock_http(
        httpx.Response(
            200,
            json={
                "model": "claude-sonnet-5",
                "content": '{"blocks":[]}',
                "usage": {},
            },
        )
    )

    result = complete(AiHereClient(settings), "claude-sonnet-5")

    assert result.model == "claude-sonnet-5"
    assert json.loads(requests[0].content)["model"] == "claude-sonnet-5"


@pytest.mark.parametrize("provider", ["aihere", "amvera", "tavily"])
@pytest.mark.parametrize(
    "error,code,status",
    [
        (httpx.ReadTimeout("private-details"), "timeout", 504),
        (httpx.ConnectError("private-details"), "connection_error", 502),
    ],
)
def test_network_errors(settings, mock_http, provider, error, code, status):
    mock_http(error=error)

    with pytest.raises(ProviderError) as caught:
        if provider == "aihere":
            complete(AiHereClient(settings))
        elif provider == "amvera":
            complete(AmveraClient(settings))
        else:
            asyncio.run(TavilyClient(settings).search("Question", False))

    assert caught.value.code == f"{provider}_{code}"
    assert caught.value.status_code == status
    assert "private-details" not in str(caught.value)


@pytest.mark.parametrize("content", [None, "", '{"blocks": []}', '{"blocks":'])
def test_output_limit_is_detected_even_with_nonempty_content(
    settings, mock_http, content
):
    mock_http(
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "content": content,
                            "reasoning_content": "private-reasoning",
                        },
                    }
                ],
                "usage": {"completion_tokens": 2000},
            },
        )
    )

    with pytest.raises(ProviderError) as caught:
        complete(AmveraClient(settings))

    assert caught.value.code == "amvera_output_limit"
    assert "MAX_OUTPUT_TOKENS=2000" in str(caught.value)
    assert "private-reasoning" not in str(caught.value)


@pytest.mark.parametrize("provider", ["aihere", "amvera", "tavily"])
@pytest.mark.parametrize(
    "status,code",
    [
        (400, "invalid_request"),
        (401, "authentication_error"),
        (403, "authorization_error"),
        (402, "billing_error"),
        (429, "rate_limit"),
        (500, "gateway_error"),
        (502, "upstream_error"),
        (503, "upstream_error"),
        (504, "upstream_error"),
        (418, "http_error"),
    ],
)
def test_http_errors_are_classified_without_response_body(
    settings, mock_http, caplog, provider, status, code
):
    mock_http(
        httpx.Response(
            status,
            json={"error": {"message": "private-provider-body private-test-key"}},
        )
    )
    caplog.set_level(logging.WARNING, logger="tracking_journal_ai")

    with pytest.raises(ProviderError) as caught:
        if provider == "aihere":
            complete(AiHereClient(settings))
        elif provider == "amvera":
            complete(AmveraClient(settings))
        else:
            asyncio.run(TavilyClient(settings).search("private-prompt", False))

    assert caught.value.code == f"{provider}_{code}"
    assert caught.value.status_code == 502
    assert f"HTTP {status}" in str(caught.value)
    assert f"{provider}_{code}" in caplog.text
    for private in ("private-provider-body", "private-test-key", "private-prompt"):
        assert private not in str(caught.value)
        assert private not in caplog.text


@pytest.mark.parametrize("provider", ["aihere", "amvera", "tavily"])
def test_invalid_json(settings, mock_http, provider):
    mock_http(httpx.Response(200, content=b"not JSON"))

    with pytest.raises(ProviderError) as caught:
        if provider == "aihere":
            complete(AiHereClient(settings))
        elif provider == "amvera":
            complete(AmveraClient(settings))
        else:
            asyncio.run(TavilyClient(settings).search("Question", False))

    assert caught.value.code == f"{provider}_invalid_json"


def test_missing_configuration_does_not_call_provider(mock_http):
    requests = mock_http(httpx.Response(200, json={}))
    for provider, operation in (
        ("aihere", AiHereClient(Settings()).complete([])),
        ("amvera", AmveraClient(Settings()).complete([])),
        ("tavily", TavilyClient(Settings()).search("Question", False)),
    ):
        with pytest.raises(ProviderError) as caught:
            asyncio.run(operation)
        assert caught.value.code == f"{provider}_configuration_error"
        assert caught.value.status_code == 503
    assert requests == []


class StubCompletionClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    async def complete(self, messages, model=None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.parametrize(
    "code",
    [
        "aihere_timeout",
        "aihere_connection_error",
        "aihere_rate_limit",
        "aihere_gateway_error",
        "aihere_upstream_error",
    ],
)
def test_failover_uses_amvera_for_transient_aihere_errors(code, caplog):
    primary = StubCompletionClient(
        error=ProviderError("aihere", "Temporary failure.", code=code.removeprefix("aihere_"))
    )
    fallback = StubCompletionClient(
        result=CompletionResult("fallback output", None, "backup-model")
    )
    client = FailoverClient(primary, fallback)

    result = asyncio.run(client.complete([{"role": "user", "content": "prompt"}]))

    assert result.model == "backup-model"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert "provider=aihere" in caplog.text


@pytest.mark.parametrize(
    "code",
    ["aihere_configuration_error", "aihere_authentication_error", "aihere_billing_error"],
)
def test_failover_does_not_hide_non_transient_aihere_errors(code):
    primary = StubCompletionClient(
        error=ProviderError("aihere", "Permanent failure.", code=code.removeprefix("aihere_"))
    )
    fallback = StubCompletionClient()

    with pytest.raises(ProviderError) as caught:
        asyncio.run(FailoverClient(primary, fallback).complete([]))

    assert caught.value.code == code
    assert fallback.calls == 0


def test_success_preserves_text_and_usage(settings, mock_http):
    text = '{"blocks":[{"type":"paragraph","text":"Answer","citations":[]}]}'
    usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    requests = mock_http(
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {**usage, "other": "ignored"},
            },
        )
    )

    result = complete(AmveraClient(settings))
    assert (result.content, result.usage, result.model) == (
        text,
        usage,
        settings.amvera_model,
    )
    sent = json.loads(requests[0].content)
    assert sent["max_tokens"] == settings.max_output_tokens
    assert sent["response_format"] == {"type": "json_object"}
    assert len(requests) == 1


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/v1/answers", {"question": "Question"}),
        ("/v1/answers/events", {"question": "Question"}),
        ("/v1/edits", {"action": "rewrite", "text": "Original"}),
        ("/v1/edits/events", {"action": "rewrite", "text": "Original"}),
    ],
)
@pytest.mark.parametrize(
    "choice,code",
    [
        ({"content": None}, "aihere_empty_completion"),
        (
            {"content": "", "finish_reason": "length"},
            "aihere_output_limit",
        ),
    ],
)
def test_error_codes_reach_json_and_sse_without_retries(
    settings, mock_http, endpoint, payload, choice, code
):
    requests = mock_http(httpx.Response(200, json=choice))
    client = TestClient(create_app(settings))

    response = client.post(endpoint, json=payload)

    if endpoint.endswith("/events"):
        assert response.status_code == 200
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        error = next(event for event in events if event.get("code") == code)
        assert error["message"]
        assert "event: error" in response.text
        assert "event: result" not in response.text
    else:
        assert response.status_code == 502
        assert response.json()["error"]["code"] == code
    assert len(requests) == 1


def test_aihere_transient_failure_falls_back_to_amvera(settings, monkeypatch):
    original_client = httpx.AsyncClient
    requests = []
    answer = json.dumps(
        {"blocks": [{"type": "paragraph", "text": "Backup answer.", "citations": []}]}
    )

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/chats/completions"):
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": answer}, "finish_reason": "stop"}
                ]
            },
        )

    monkeypatch.setattr(
        "app.api.providers.httpx.AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )

    response = TestClient(create_app(settings)).post(
        "/v1/answers", json={"question": "Question"}
    )

    assert response.status_code == 200
    assert response.json()["model"] == settings.amvera_model
    assert response.json()["blocks"][0]["text"] == "Backup answer."
    assert [request.url.path for request in requests] == [
        "/api/v1/chats/completions",
        "/v1/chat/completions",
    ]


@pytest.mark.parametrize("endpoint", ["/v1/answers", "/v1/answers/events"])
def test_search_error_code_is_preserved(settings, mock_http, endpoint):
    mock_http(httpx.Response(429, json={"error": {"message": "private-body"}}))
    response = TestClient(create_app(settings)).post(
        endpoint, json={"question": "Question", "web_search": True}
    )

    if endpoint.endswith("/events"):
        assert "tavily_rate_limit" in response.text
        assert "event: error" in response.text
    else:
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "tavily_rate_limit"
    assert "private-body" not in response.text


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/v1/answers", {"question": "Question"}),
        ("/v1/answers/events", {"question": "Question"}),
        ("/v1/edits", {"action": "rewrite", "text": "Original"}),
        ("/v1/edits/events", {"action": "rewrite", "text": "Original"}),
        ("/v1/answers", {"question": "Question", "web_search": True}),
        ("/v1/answers/events", {"question": "Question", "web_search": True}),
    ],
)
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("body", ['{"error":"тест"}', "plain text\nerror", ""])
def test_http_error_body_is_opt_in_for_json_and_sse(
    settings, mock_http, caplog, endpoint, payload, enabled, body
):
    mock_http(httpx.Response(404, text=body))
    caplog.set_level(logging.WARNING, logger="tracking_journal_ai")
    client = TestClient(
        create_app(replace(settings, expose_provider_error_body=enabled))
    )

    response = client.post(endpoint, json=payload)

    if endpoint.endswith("/events"):
        assert response.status_code == 200
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        error = next(event for event in events if "code" in event)
        assert "event: error" in response.text
    else:
        assert response.status_code == 502
        error = response.json()["error"]

    assert error["code"] == (
        "tavily_http_error" if payload.get("web_search") else "aihere_http_error"
    )
    if enabled:
        assert error["provider_response"] == {"status": 404, "body": body}
    else:
        assert "provider_response" not in error
    if body:
        assert body not in caplog.text


@pytest.mark.parametrize(
    "value,expected",
    [("true", True), ("1", True), (" false ", False), ("0", False)],
)
def test_provider_error_body_setting(monkeypatch, value, expected):
    monkeypatch.setenv("EXPOSE_PROVIDER_ERROR_BODY", value)
    assert Settings.from_env().expose_provider_error_body is expected


def test_invalid_provider_error_body_setting_is_rejected(monkeypatch):
    monkeypatch.setenv("EXPOSE_PROVIDER_ERROR_BODY", "yes")
    with pytest.raises(ValueError, match="EXPOSE_PROVIDER_ERROR_BODY"):
        Settings.from_env()
