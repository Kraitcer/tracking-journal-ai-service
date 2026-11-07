import asyncio
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.providers import AmveraClient, ProviderError, TavilyClient
from main import create_app
from settings import Settings


@pytest.fixture
def settings():
    return Settings(
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


def complete(client):
    return asyncio.run(client.complete([{"role": "user", "content": "private-prompt"}]))


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


@pytest.mark.parametrize("provider", ["amvera", "tavily"])
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
        if provider == "amvera":
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


@pytest.mark.parametrize("provider", ["amvera", "tavily"])
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
        if provider == "amvera":
            complete(AmveraClient(settings))
        else:
            asyncio.run(TavilyClient(settings).search("Question", False))

    assert caught.value.code == f"{provider}_{code}"
    assert caught.value.status_code == status
    assert "private-details" not in str(caught.value)


@pytest.mark.parametrize("provider", ["amvera", "tavily"])
def test_invalid_json(settings, mock_http, provider):
    mock_http(httpx.Response(200, content=b"not JSON"))

    with pytest.raises(ProviderError) as caught:
        if provider == "amvera":
            complete(AmveraClient(settings))
        else:
            asyncio.run(TavilyClient(settings).search("Question", False))

    assert caught.value.code == f"{provider}_invalid_json"


def test_missing_configuration_does_not_call_provider(mock_http):
    requests = mock_http(httpx.Response(200, json={}))
    for provider, operation in (
        ("amvera", AmveraClient(Settings()).complete([])),
        ("tavily", TavilyClient(Settings()).search("Question", False)),
    ):
        with pytest.raises(ProviderError) as caught:
            asyncio.run(operation)
        assert caught.value.code == f"{provider}_configuration_error"
        assert caught.value.status_code == 503
    assert requests == []


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

    assert complete(AmveraClient(settings)) == (text, usage)
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
        ({"message": {"content": None}}, "amvera_empty_completion"),
        (
            {"message": {"content": ""}, "finish_reason": "length"},
            "amvera_output_limit",
        ),
    ],
)
def test_error_codes_reach_json_and_sse_without_retries(
    settings, mock_http, endpoint, payload, choice, code
):
    requests = mock_http(httpx.Response(200, json={"choices": [choice]}))
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
