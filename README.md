# Tracking Journal AI Service

Standalone FastAPI service for experimenting with AI answers, web research,
supplied journal records, and text edits. It does not connect to the Tracking
Journal client, NestJS server, or application database.

## Requirements

- Python 3.14
- The prepared `.venv` and Pipenv environment
- An Amvera LLM Inference API key and a model name for real completions
- A Tavily API key only for web-search requests

Copy `.env.example` to `.env` and set `AMVERA_API_KEY`, `AMVERA_MODEL`, and,
when using web search, `TAVILY_API_KEY`. The service reads environment variables
directly; the `.env` file is a configuration template and is not loaded
automatically. In PowerShell, load it with:

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

## API examples

Use the **Try it out** button in Swagger. The service accepts and returns JSON.
Provider requests are made only when an endpoint is called.

### Answer without external search

`POST /v1/answers`

```json
{
  "question": "Помоги сформулировать цель на неделю."
}
```

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
| `AMVERA_API_KEY` | unset | Amvera LLM Inference API credential |
| `AMVERA_BASE_URL` | `https://inference.waw0.amvera.ru/v1` | OpenAI-compatible API base URL |
| `AMVERA_MODEL` | unset | Model identifier available to the account |
| `TAVILY_API_KEY` | unset | Enables optional Tavily web search |
| `REQUEST_TIMEOUT_SECONDS` | `45` | Timeout for each provider request |
| `MAX_OUTPUT_TOKENS` | `2000` | Maximum model completion size |
| `MAX_CONCURRENT_REQUESTS` | `3` | Maximum active AI requests |
| `MAX_SEARCH_RESULTS` | `5` | Maximum web results used |
| `MAX_SOURCE_CHARS` | `6000` | Maximum source text per result |
| `MAX_CONTEXT_CHARS` | `24000` | Combined context size limit |

The Amvera endpoint, model list, and model capabilities can change. Confirm the
current account-specific model name and API details in
[Amvera LLM Inference documentation](https://docs.amvera.ru/LLM/doc-inference-ru.html).
The adapter requests JSON mode and independently validates output with Pydantic;
if a selected model/provider does not support this response format, the provider
error is surfaced. No live paid provider call is made by the automated tests.

Tavily Search uses `POST https://api.tavily.com/search`, `include_raw_content`,
and its optional `include_images` result. The service does not crawl arbitrary
URLs or download images.

## Errors and privacy

Errors use the shape `{"error":{"code":"...","message":"..."}}`, with HTTP
validation details for invalid requests. Provider credentials and provider
response bodies are not included in error messages. Logs do not include prompts,
records, or generated text.

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
