"""Pydantic request / response models (these drive the OpenAPI docs at /docs)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.validation import MAX_MESSAGE_LENGTH, extract_links, validate_message

EXAMPLE_MESSAGE = (
    "Check out our latest business platform and grow your online visibility. "
    "https://example.com"
)


class PostingRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"message": EXAMPLE_MESSAGE}]})

    message: str = Field(
        ...,
        description=(
            f"Short message (max {MAX_MESSAGE_LENGTH} chars) containing exactly one "
            "http(s) CTA link."
        ),
        json_schema_extra={"maxLength": MAX_MESSAGE_LENGTH},
    )

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        return validate_message(value)

    @property
    def cta_url(self) -> str:
        return extract_links(self.message)[0]


class PostStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class PlatformResult(BaseModel):
    platform: str = Field(..., examples=["Mastodon"])
    status: PostStatus
    posted_url: str | None = Field(None, examples=["https://mastodon.social/@me/1132"])
    public_access: bool = Field(
        False, description="Verified by fetching posted_url anonymously (no credentials)."
    )
    date: str | None = Field(None, description="Posting date (UTC, YYYY-MM-DD)", examples=["2026-11-15"])
    time: str | None = Field(None, description="Posting time (UTC, HH:MM:SS)", examples=["10:30:00"])
    error: str | None = None


class PostingSummary(BaseModel):
    total: int
    succeeded: int
    failed: int


class PostingResponse(BaseModel):
    success: bool = Field(..., description="True when at least one platform succeeded.")
    summary: PostingSummary
    results: list[PlatformResult]


class ErrorDetail(BaseModel):
    field: str
    message: str


class ValidationErrorResponse(BaseModel):
    success: bool = False
    error: str = "Validation failed"
    details: list[ErrorDetail]
