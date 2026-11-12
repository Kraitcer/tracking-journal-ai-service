# Tracking Journal AI Service

Standalone FastAPI service for experimenting with AI answers, web research,
supplied journal records, and text edits. It does not connect to the Tracking
Journal client, NestJS server, or application database.

## Requirements

- Python 3.14
- The prepared `.venv` and Pipenv environment
- An AIhere API key and supported chat model for primary completions
- An Amvera LLM Inference API key and model name for automatic fallback
- A Tavily API key only for web-search requests

Copy `.env.example` to `.env` and set `AIHERE_API_KEY`, `AIHERE_MODEL`,
`AMVERA_API_KEY`, and `AMVERA_MODEL`; set `TAVILY_API_KEY` when using web search.
The service reads environment variables directly; the `.env` file is a
configuration template and is not loaded automatically. In PowerShell, load it
with:

```powershell
Get-Content .env | Where-Object { $_ -match '^[A-Za-z_][A-Za-z0-9_]*=' } | ForEach-Object {
  $name, $value = $_ -split '=', 2
  Set-Item -Path "Env:$name" -Value $value
}
```

Do not commit `.env` or paste real API keys into Swagger examples.

## Run locally and open Swagger

From this directory:

```powershell
.\.venv\Scripts\uvicorn.exe main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). The OpenAPI schema
is available at `/openapi.json`; `/health` is local-only and does not call any
external provider.

Alternatively, activate the prepared venv and run Uvicorn:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn main:app --host 127.0.0.1 --port 8000
```

The service binds to localhost by default in these commands and does not enable
permissive CORS.

## Run in the local Docker Compose stack

From the repository root, optionally copy `.env.example` to `.env` in this
directory and set `AIHERE_API_KEY`, `AIHERE_MODEL`, `AMVERA_API_KEY`, and
`AMVERA_MODEL`; set `TAVILY_API_KEY` when using web search. Compose can start
the service without this file, but real AI requests require the relevant
provider settings.

```powershell
docker compose up -d --build ai
docker compose logs -f ai
```

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). The port is
published on localhost only. Saving Python files in `main.py`, `settings.py`,
or `app/` reloads the application automatically; changes to dependencies or
the Dockerfile require rebuilding with `docker compose up -d --build ai`.
This Compose service is for local development and is not part of the Amvera
deployment configuration.

## API examples

Use the **Try it out** button in Swagger. The service accepts and returns JSON.
Provider requests are made only when an endpoint is called.

### Answer without external search

`POST /v1/answers`

```json
{
  "question": "Помоги сформулировать цель на неделю.",
  "model": "gpt-5-6-luna"
}
```

The optional `model` field selects an AIhere model for this request. It is
available on `/v1/answers`, `/v1/edits`, and their SSE variants. If omitted,
the service uses `AIHERE_MODEL`. Accepted IDs reported by AIhere are
`gemini-3-8-flash`, `gemini-3-8-flash-openai`, `claude-haiku-5-5`,
`claude-sonnet-5-5`, `claude-opus-5-5`, `claude-fable-5`, `gpt-6-luna`,
`gpt-5-6-terra`, `gpt-6-1-sol`, `gpt-6-astra`, `kimi-k3`,
`deepseek-v4-1-flash`, and `grok-4-7`. Unknown model IDs are rejected with
HTTP 422. If AIhere fails over to Amvera, the configured `AMVERA_MODEL` is
used instead.

### Answer with web search and images

`POST /v1/answers`

```json
{
  "question": "Какие существуют практики планирования недели?",
  "web_search": true,
  "include_images": true
}
```

`include_images` requires `web_search`. Images are returned only when Tavily
provides image URLs associated with a search result. The response includes
source IDs, titles, URLs, and image blocks. A search failure or empty result set
is returned as an explicit error, not as an ungrounded answer.

### Answer using supplied local records

`POST /v1/answers`

```json
{
  "question": "Какие проекты я запланировал?",
  "records": [
    {
      "id": "project-record-1",
      "entity_type": "project",
      "entity_id": "project-1",
      "title": "Изучить английский",
      "text": "Заниматься по 20 минут четыре раза в неделю."
    },
    {
      "id": "goal-record-1",
      "entity_type": "goal",
      "entity_id": "goal-1",
      "title": "Пройти курс",
      "text": "Завершить текущий курс до конца месяца."
    }
  ]
}
```

Records are request-scoped context only. This service does not persist, index, or
search an archive. If `web_search` is also enabled, only the question is sent to
Tavily; supplied record contents are sent to the configured LLM provider, not to
the web-search provider.

### Rewrite text

`POST /v1/edits`

```json
{
  "action": "rewrite",
  "model": "claude-sonnet-5",
  "text": "Здесь исходный текст описания.",
  "instruction": "Сделай формулировку короче и яснее."
}
```

### Continue text

`POST /v1/edits`

```json
{
  "action": "continue",
  "text": "Начало заметки...",
  "instruction": "Продолжи в том же стиле, не добавляя конкретных фактов."
}
```

Edit endpoints return a suggestion only; they never save or overwrite the input.
They do not use web search.

### Event streams

- `POST /v1/answers/events`
- `POST /v1/edits/events`

These endpoints return Server-Sent Events (`started`, `progress`, `result`, or
`error`). They stream stage events and a final structured result, not model
tokens. The regular JSON endpoints are easier to inspect in Swagger.

## Response shape and source guarantees

Answer responses have a `request_id`, typed `blocks`, `sources`, `warnings`,
`model`, and provider token usage when available. Blocks are paragraphs,
headings, lists, tables, or service-added images; the API does not emit HTML or
BlockNote JSON. Table row widths are validated.

Web and local sources receive IDs from the service. The model may cite only IDs
included in its request; unknown IDs and malformed output trigger one repair
attempt and then an explicit error. Checking an ID confirms that a source was
provided, not that it truly supports every statement. Review citations before
relying on a generated answer.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AIHERE_API_KEY` | unset | Primary AIhere chat API credential |
| `AIHERE_BASE_URL` | `https://api.aihere.ru/api/v1` | AIhere API base URL |
| `AIHERE_MODEL` | unset | AIhere model ID, e.g. `gpt-5-6-luna` |
| `AMVERA_API_KEY` | unset | Amvera LLM Inference API credential |
| `AMVERA_BASE_URL` | `https://inference.waw0.amvera.ru/v1` | OpenAI-compatible API base URL |
| `AMVERA_MODEL` | unset | Amvera fallback model identifier |
| `TAVILY_API_KEY` | unset | Enables optional Tavily web search |
| `REQUEST_TIMEOUT_SECONDS` | `45` | Timeout for each provider request |
| `MAX_OUTPUT_TOKENS` | `2000` | Maximum model completion size |
| `EXPOSE_PROVIDER_ERROR_BODY` | `false` | Expose full upstream HTTP error responses for local debugging |
| `MAX_CONCURRENT_REQUESTS` | `3` | Maximum active AI requests |
| `MAX_SEARCH_RESULTS` | `5` | Maximum web results used |
| `MAX_SOURCE_CHARS` | `6000` | Maximum source text per result |
| `MAX_CONTEXT_CHARS` | `24000` | Combined context size limit |

AIhere is the primary chat provider; Amvera is used as fallback for timeouts,
connection failures, rate limits, and upstream `5xx` errors. Authentication,
billing, configuration, invalid-request, and malformed-output errors are
returned rather than hidden by switching providers. Every request starts with
AIhere; failover is per-request and does not change provider state. As a result,
the response `model` field identifies the model that actually produced it.

AIhere's documented base URL is `https://api.aihere.ru/api/v1` and its endpoint
is `POST /chats/completions`. Its non-streaming response uses top-level
`content`, `finish_reason`, and `usage` fields. The current supported model IDs
are listed in the [AIhere chat model documentation](https://api.aihere.ru/about/chat/models);
the API documents a 30-request/minute limit for completions. The request uses
`stream: false` and does not send `response_format`, which is not listed among
the documented parameters. Structured JSON is requested in the prompt and
independently validated by the service with Pydantic.

The Amvera endpoint, model list, and model capabilities can change. Confirm the
current account-specific model name and API details in
[Amvera LLM Inference documentation](https://docs.amvera.ru/LLM/doc-inference-ru.html).
No live paid provider call is made by the automated tests.

Tavily Search uses `POST https://api.tavily.com/search`, `include_raw_content`,
and its optional `include_images` result. The service does not crawl arbitrary
URLs or download images.

## Errors and privacy

Errors use the shape `{"error":{"code":"...","message":"..."}}`, with HTTP
validation details for invalid requests. By default, provider response bodies
are not included. Logs do not include prompts, records, or generated text.

For local debugging only, set `EXPOSE_PROVIDER_ERROR_BODY=true` in this
directory's `.env`, then recreate the Compose container with
`docker compose up -d --force-recreate ai` from the repository root. For a
direct Uvicorn launch, set the environment variable before starting the process.
HTTP errors from AIhere, Amvera, and Tavily then include
`"provider_response":{"status":404,"body":"..."}` inside the JSON `error`
object or SSE `error` event. `body` is the complete response decoded as text,
including non-JSON responses; it is not written to logs. It may contain API
keys, prompts, records, or other sensitive information. Anyone who can call
the API can see it: use only on a trusted local instance, inspect it privately,
and set the variable back to `false` and recreate the container afterward.

Provider errors have provider-specific codes instead of generic errors. The
table below uses the `amvera_` prefix; AIhere uses the corresponding `aihere_`
prefix, while web-search errors use `tavily_`. These codes are also returned in
SSE `error` events.

| Code | Meaning |
|---|---|
| `amvera_invalid_response` | Malformed completion envelope, missing fields, or incorrect field types |
| `amvera_empty_completion` | Final `content` is null, empty, or whitespace-only |
| `amvera_output_limit` | `finish_reason=length`; generation stopped at the token limit |
| `amvera_invalid_json` | Provider response body is not valid JSON |
| `amvera_invalid_request` | Provider returned HTTP 400 |
| `amvera_authentication_error` | Provider returned HTTP 401 |
| `amvera_authorization_error` | Provider returned HTTP 403 |
| `amvera_billing_error` | Provider returned HTTP 402 |
| `amvera_rate_limit` | Provider returned HTTP 429 |
| `amvera_gateway_error` | Provider returned HTTP 500 |
| `amvera_upstream_error` | Provider returned HTTP 502, 503, or 504 |
| `amvera_http_error` | Other unsuccessful provider HTTP status |
| `amvera_configuration_error` | Required provider settings are missing |
| `amvera_timeout` | Local provider request timed out |
| `amvera_connection_error` | Provider request failed at the transport layer |

Provider errors use provider-specific codes such as `aihere_upstream_error`
and `amvera_upstream_error`. Upstream HTTP failures still return HTTP 502 from
this service, with the upstream status in the safe message; local timeouts
return 504 and missing configuration returns 503. These statuses concern the
configured provider, not the caller's authentication or billing with this
service.
Logs record the provider, error code, and service status, without provider
response bodies. A null/empty completion alone does not prove token exhaustion:
`amvera_output_limit` and `aihere_output_limit` require an explicit
`finish_reason=length`.
Limit-stopped completions are rejected even if they contain text or parseable
JSON, because they may be incomplete. Failover is attempted once for timeouts,
connection failures, rate limits, and upstream `5xx` errors. Permanent provider
errors and invalid structured model output do not trigger failover. The existing
single repair attempt for invalid structured model output remains unchanged
(`invalid_model_output`). A fallback call may be billable even if the primary
provider timed out after processing the request. Both providers receive the
same user prompt and context.

Requests have bounded field sizes, a 1 MB Content-Length limit, a combined
context cap, provider timeouts, and a concurrent request limit. This service is
for local testing only: it has no authentication and must not be exposed publicly
or connected directly to a browser. AI inputs are sent to the configured model
provider. When web search is enabled, the user's question is also sent to Tavily.

Before integrating through NestJS, add service-to-service authentication and
have NestJS authenticate the user, authorize and select records, apply usage
limits, and only then call this API. A user ID supplied by a client is not an
authorization mechanism.

## Tests

From this directory:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
```

Tests use fake providers and do not require credentials, internet access, or
paid API calls.
