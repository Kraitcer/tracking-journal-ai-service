import json

from fastapi.testclient import TestClient

from app.api.providers import CompletionResult, ProviderError
from app.services.service import AIService
from main import create_app
from settings import Settings


class FakeAmvera:
    def __init__(self, outputs=None):
        self.outputs = list(outputs or [])
        self.messages = []
        self.models = []

    async def complete(self, messages, model=None):
        self.messages.append(messages)
        self.models.append(model)
        if self.outputs:
            return CompletionResult(
                self.outputs.pop(0), {"total_tokens": 12}, model or "test-model"
            )
        request = json.loads(messages[1]["content"])
        source_ids = request.get("available_source_ids", [])
        return CompletionResult(
            json.dumps(
                {
                    "blocks": [
                        {
                            "type": "paragraph",
                            "text": "A concise answer.",
                            "citations": source_ids[:1],
                        }
                    ]
                }
            ),
            {"total_tokens": 12},
            model or "test-model",
        )


class FakeTavily:
    def __init__(self, results=None):
        self.results = results or {
            "results": [
                {
                    "title": "Example source",
                    "url": "https://example.com/article",
                    "content": "A short source excerpt.",
                    "raw_content": "Full source text.",
                    "images": [
                        {
                            "url": "https://example.com/image.jpg",
                            "description": "An example image",
                        }
                    ],
                }
            ]
        }
        self.queries = []

    async def search(self, query, include_images):
        self.queries.append((query, include_images))
        return self.results


def build_client(amvera=None, tavily=None, settings=None):
    app = create_app(
        settings
        or Settings(
            amvera_api_key="test-key",
            amvera_model="test-model",
            tavily_api_key="test-search-key",
        )
    )
    app.state.ai_service = AIService(
        settings
        or Settings(
            amvera_api_key="test-key",
            amvera_model="test-model",
            tavily_api_key="test-search-key",
        ),
        amvera=amvera or FakeAmvera(),
        tavily=tavily or FakeTavily(),
    )
    return TestClient(app)


def test_health_and_swagger_are_available_without_provider_calls():
    client = build_client()

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/v1/answers" in schema["paths"]
    assert "/v1/answers/events" in schema["paths"]


def test_answer_without_web_search_does_not_call_tavily():
    tavily = FakeTavily()
    client = build_client(tavily=tavily)

    response = client.post("/v1/answers", json={"question": "What is a habit?"})

    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert tavily.queries == []


def test_request_can_select_aihere_model_for_answer_and_edit():
    model = "gemini-3-8-flash"
    answer_client_model = FakeAmvera()
    edit_client_model = FakeAmvera([json.dumps({"suggested_text": "Edited."})])

    answer = build_client(amvera=answer_client_model).post(
        "/v1/answers",
        json={"question": "Question", "model": model},
    )
    edit = build_client(amvera=edit_client_model).post(
        "/v1/edits",
        json={"action": "rewrite", "text": "Original", "model": model},
    )

    assert answer.status_code == 200
    assert answer.json()["model"] == model
    assert edit.status_code == 200
    assert edit.json()["model"] == model
    assert answer_client_model.models == [model]
    assert edit_client_model.models == [model]


def test_request_rejects_unlisted_aihere_model():
    amvera = FakeAmvera()
    response = build_client(amvera=amvera).post(
        "/v1/answers",
        json={"question": "Question", "model": "gemini-3-6-flash"},
    )

    assert response.status_code == 422
    assert amvera.models == []


def test_web_search_sources_citations_and_images_are_bound_by_service():
    tavily = FakeTavily()
    client = build_client(tavily=tavily)

    response = client.post(
        "/v1/answers",
        json={
            "question": "Summarize this topic.",
            "web_search": True,
            "include_images": True,
        },
    )

    data = response.json()
    assert response.status_code == 200
    assert tavily.queries == [("Summarize this topic.", True)]
    assert data["sources"][0]["source_id"] == "web-1"
    assert data["blocks"][0]["citations"] == ["web-1"]
    assert data["blocks"][1]["type"] == "image"
    assert data["blocks"][1]["source_id"] == "web-1"
    assert data["blocks"][1]["url"] == "https://example.com/image.jpg"


def test_web_search_with_no_results_returns_explicit_error():
    client = build_client(tavily=FakeTavily({"results": []}))

    response = client.post(
        "/v1/answers",
        json={"question": "Find a source.", "web_search": True},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "no_search_results"


def test_record_context_is_sent_to_model_but_not_to_search_provider():
    tavily = FakeTavily()
    amvera = FakeAmvera()
    client = build_client(amvera=amvera, tavily=tavily)

    response = client.post(
        "/v1/answers",
        json={
            "question": "What did I plan?",
            "web_search": True,
            "records": [
                {
                    "id": "record-1",
                    "entity_type": "goal",
                    "entity_id": "goal-1",
                    "title": "Read more",
                    "text": "I plan to read one book per month.",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert tavily.queries == [("What did I plan?", False)]
    model_user_context = amvera.messages[0][1]["content"]
    assert "I plan to read one book per month." in model_user_context
    assert response.json()["sources"][1]["record_id"] == "record-1"
    assert response.json()["blocks"][0]["citations"] == ["web-1"]


def test_unknown_source_citation_is_rejected_after_one_repair_attempt():
    bad = json.dumps(
        {"blocks": [{"type": "paragraph", "text": "Unsupported.", "citations": ["other-1"]}]}
    )
    client = build_client(amvera=FakeAmvera([bad, bad]))

    response = client.post(
        "/v1/answers",
        json={
            "question": "Use this source.",
            "web_search": True,
        },
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_model_output"


def test_edit_returns_suggestion_without_using_web_or_mutating_source():
    original = "My original note."
    amvera = FakeAmvera(
        [json.dumps({"suggested_text": "My edited suggestion."})]
    )
    tavily = FakeTavily()
    client = build_client(amvera=amvera, tavily=tavily)

    response = client.post(
        "/v1/edits",
        json={"action": "rewrite", "text": original, "instruction": "Be concise."},
    )

    assert response.status_code == 200
    assert response.json()["suggested_text"] == "My edited suggestion."
    assert original == "My original note."
    assert tavily.queries == []


def test_continue_requires_instruction():
    response = build_client().post(
        "/v1/edits",
        json={"action": "continue", "text": "A sentence."},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "instruction_required"


def test_invalid_table_row_is_retried_then_reported():
    invalid_table = json.dumps(
        {
            "blocks": [
                {
                    "type": "table",
                    "columns": ["A", "B"],
                    "rows": [["only one"]],
                    "citations": [],
                }
            ]
        }
    )
    client = build_client(amvera=FakeAmvera([invalid_table, invalid_table]))

    response = client.post("/v1/answers", json={"question": "Make a table."})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_model_output"


def test_invalid_request_and_oversized_content_length_are_rejected():
    client = build_client()

    invalid = client.post("/v1/answers", json={"question": ""})
    invalid_images = client.post(
        "/v1/answers",
        json={"question": "Need an image.", "include_images": True},
    )
    too_large = client.post(
        "/v1/answers",
        content="{}",
        headers={"content-length": "1000001", "content-type": "application/json"},
    )

    assert invalid.status_code == 422
    assert invalid_images.status_code == 422
    assert "include_images requires web_search=true" in invalid_images.text
    assert too_large.status_code == 413


def test_sse_endpoint_streams_progress_and_result():
    client = build_client()

    with client.stream(
        "POST",
        "/v1/answers/events",
        json={"question": "Stream this answer."},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: started" in body
    assert "event: progress" in body
    assert "event: result" in body


def test_provider_failure_is_reported_without_secret_details():
    class BrokenAmvera:
        async def complete(self, _, model=None):
            raise ProviderError("amvera", "Configured key rejected.", 503)

    response = build_client(amvera=BrokenAmvera()).post(
        "/v1/answers",
        json={"question": "Answer this."},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "amvera_error"
    assert "test-key" not in response.text
