"""Схемы проверки запросов, структурированных AI-ответов и источников данных."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

EntityType = Literal["project", "goal", "task", "subTask"]
AIHereModel = Literal[
    "gemini-3-8-flash",
    "gemini-3-8-flash-openai",
    "claude-haiku-5-5",
    "claude-sonnet-5-5",
    "claude-opus-5-5",
    "claude-fable-5",
    "gpt-6-luna",
    "gpt-5-6-terra",
    "gpt-6-1-sol",
    "gpt-6-astra",
    "kimi-k3",
    "deepseek-v4-1-flash",
    "grok-4-7",
]


class UserRecord(BaseModel):
    """Запись проекта, цели, задачи или подзадачи для передачи модели как контекста."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    entity_type: EntityType
    entity_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=12000)


class AnswerRequest(BaseModel):
    """Запрос ответа на вопрос с необязательным веб-поиском и записями пользователя."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    model: AIHereModel | None = None
    web_search: bool = False
    include_images: bool = False
    records: list[UserRecord] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def require_web_search_for_images(self) -> "AnswerRequest":
        """Отклоняет запрос изображений без включённого веб-поиска."""
        if self.include_images and not self.web_search:
            raise ValueError("include_images requires web_search=true.")
        return self


class EditRequest(BaseModel):
    """Запрос переписывания или продолжения текста с инструкцией и контекстом."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["rewrite", "continue"]
    model: AIHereModel | None = None
    text: str = Field(min_length=1, max_length=12000)
    instruction: str | None = Field(default=None, max_length=2000)
    context: str | None = Field(default=None, max_length=6000)


class SourceReference(BaseModel):
    """Ссылка на источник по его идентификатору, без дублирования данных источника."""

    source_id: str = Field(min_length=1, max_length=100)


class ParagraphBlock(BaseModel):
    """Абзац AI-ответа с текстом и идентификаторами подтверждающих источников."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["paragraph"]
    text: str = Field(min_length=1, max_length=8000)
    citations: list[str] = Field(default_factory=list, max_length=10)


class HeadingBlock(BaseModel):
    """Заголовок AI-ответа первого, второго или третьего уровня со ссылками на источники."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["heading"]
    level: Literal[1, 2, 3]
    text: str = Field(min_length=1, max_length=500)
    citations: list[str] = Field(default_factory=list, max_length=10)


class ListBlock(BaseModel):
    """Маркированный или нумерованный список AI-ответа со ссылками на источники."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["list"]
    ordered: bool = False
    items: list[str] = Field(min_length=1, max_length=50)
    citations: list[str] = Field(default_factory=list, max_length=10)


class TableBlock(BaseModel):
    """Таблица AI-ответа с заголовками столбцов, строками и ссылками на источники."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["table"]
    columns: list[str] = Field(min_length=1, max_length=12)
    rows: list[list[str]] = Field(min_length=1, max_length=50)
    citations: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_row_widths(self) -> "TableBlock":
        """Проверяет, что число ячеек каждой строки совпадает с числом столбцов."""
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Every table row must match the number of columns.")
        return self


class ImageBlock(BaseModel):
    """Изображение в ответе с HTTP(S)-адресом, описанием и идентификатором источника."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["image"]
    url: HttpUrl
    alt_text: str = Field(default="", max_length=1000)
    source_id: str = Field(min_length=1, max_length=100)


AnswerBlock = Annotated[
    ParagraphBlock | HeadingBlock | ListBlock | TableBlock | ImageBlock,
    Field(discriminator="type"),
]


class Source(BaseModel):
    """Данные веб-источника или локальной записи, на которые ссылаются блоки ответа."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    kind: Literal["web", "local"]
    title: str
    url: HttpUrl | None = None
    snippet: str = ""
    record_id: str | None = None


class AnswerContent(BaseModel):
    """Структурированное содержимое ответа модели для проверки перед выдачей клиенту."""

    model_config = ConfigDict(extra="forbid")

    blocks: list[AnswerBlock] = Field(min_length=1, max_length=100)


class AnswerResponse(BaseModel):
    """Ответ API с блоками, источниками, предупреждениями и сведениями о генерации.

    Содержит идентификатор запроса, имя модели и доступную статистику токенов.
    """

    request_id: str
    blocks: list[AnswerBlock]
    sources: list[Source]
    warnings: list[str] = Field(default_factory=list)
    model: str
    usage: dict[str, int] | None = None


class EditResponse(BaseModel):
    """Результат правки с предложенным текстом без изменения исходной записи.

    Содержит идентификатор запроса, действие, имя модели и статистику токенов,
    если она доступна.
    """

    request_id: str
    action: Literal["rewrite", "continue"]
    suggested_text: str
    model: str
    usage: dict[str, int] | None = None
