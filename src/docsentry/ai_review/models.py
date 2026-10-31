"""Strict, immutable AI data contracts. Raw prompts/responses are never stored."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROMPT_VERSION = "1"


class AIVerdict(StrEnum):
    SUPPORTS_DRIFT = "supports_drift"
    LIKELY_CONSISTENT = "likely_consistent"
    UNCERTAIN = "uncertain"
    NOT_APPLICABLE = "not_applicable"


class AIReviewStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    SKIPPED_DISABLED = "skipped_disabled"
    SKIPPED_NO_ITEMS = "skipped_no_items"
    SKIPPED_INCOMPLETE_INPUT = "skipped_incomplete_input"
    UNAVAILABLE = "unavailable"
    INVALID_OUTPUT = "invalid_output"
    FAILED = "failed"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AIEvidenceRef(_Strict):
    evidence_id: str = Field(min_length=1, max_length=40)
    kind: str = Field(max_length=40)
    location: str = Field(default="", max_length=300)


class AIItemAssessment(_Strict):
    item_id: str = Field(min_length=1, max_length=200)
    verdict: AIVerdict
    explanation: str = Field(max_length=500)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=8)
    caveats: tuple[str, ...] = Field(default=(), max_length=3)
    suggested_target_id: str | None = Field(default=None, max_length=200)

    @field_validator("explanation")
    @classmethod
    def _no_urls(cls, v: str) -> str:
        if "://" in v or "](" in v:
            raise ValueError("urls_not_allowed")
        return v

    @field_validator("evidence_ids", "caveats")
    @classmethod
    def _bounded(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if any(len(x) > 300 for x in v):
            raise ValueError("too_long")
        return v


class AIReviewBatchOutput(_Strict):
    assessments: tuple[AIItemAssessment, ...] = Field(max_length=10)


class AIReviewResult(_Strict):
    status: AIReviewStatus
    assessments: tuple[AIItemAssessment, ...] = ()
    model: str = Field(default="", max_length=200)
    prompt_version: str = PROMPT_VERSION
    error_code: str | None = Field(default=None, max_length=60)
    batches: int = 0
    items_total: int = 0
    items_reviewed: int = 0
    elapsed_ms: int = 0
