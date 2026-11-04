"""Validated API request and response models."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

EntityType = Literal["project", "goal", "task", "subTask"]


class UserRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    entity_type: EntityType
    entity_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=12000)


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    web_search: bool = False
    include_images: bool = False
    records: list[UserRecord] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def require_web_search_for_images(self) -> "AnswerRequest":
        if self.include_images and not self.web_search:
            raise ValueError("include_images requires web_search=true.")
        return self


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["rewrite", "continue"]
    text: str = Field(min_length=1, max_length=12000)
    instruction: str | None = Field(default=None, max_length=2000)
    context: str | None = Field(default=None, max_length=6000)


class SourceReference(BaseModel):
    source_id: str = Field(min_length=1, max_length=100)


class ParagraphBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["paragraph"]
    text: str = Field(min_length=1, max_length=8000)
    citations: list[str] = Field(default_factory=list, max_length=10)


class HeadingBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["heading"]
    level: Literal[1, 2, 3]
    text: str = Field(min_length=1, max_length=500)
    citations: list[str] = Field(default_factory=list, max_length=10)


class ListBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["list"]
    ordered: bool = False
    items: list[str] = Field(min_length=1, max_length=50)
    citations: list[str] = Field(default_factory=list, max_length=10)


class TableBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["table"]
    columns: list[str] = Field(min_length=1, max_length=12)
    rows: list[list[str]] = Field(min_length=1, max_length=50)
    citations: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_row_widths(self) -> "TableBlock":
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Every table row must match the number of columns.")
        return self


class ImageBlock(BaseModel):
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
    model_config = ConfigDict(extra="forbid")

    source_id: str
    kind: Literal["web", "local"]
    title: str
    url: HttpUrl | None = None
    snippet: str = ""
    record_id: str | None = None


class AnswerContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocks: list[AnswerBlock] = Field(min_length=1, max_length=100)


class AnswerResponse(BaseModel):
    request_id: str
    blocks: list[AnswerBlock]
    sources: list[Source]
    warnings: list[str] = Field(default_factory=list)
    model: str
    usage: dict[str, int] | None = None


class EditResponse(BaseModel):
    request_id: str
    action: Literal["rewrite", "continue"]
    suggested_text: str
    model: str
    usage: dict[str, int] | None = None
