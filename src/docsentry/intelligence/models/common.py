from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JsonValue = Any


class Side(StrEnum):
    BASE = "base"
    HEAD = "head"


class FileClass(StrEnum):
    SOURCE = "source"
    DOC = "doc"
    CONFIG = "config"
    TEST = "test"
    OTHER = "other"
    UNSUPPORTED = "unsupported"


class Exposure(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNKNOWN = "unknown"


class Certainty(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Strength(StrEnum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"


class ConsistencyState(StrEnum):
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    NOT_EVALUABLE = "not_evaluable"


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    commit_sha: str
    line: int
    end_line: int | None = None
    column: int | None = None
    snippet: str | None = Field(default=None, max_length=120)


class ValueRepr(BaseModel):
    model_config = ConfigDict(frozen=True)
    resolved: bool
    value: JsonValue | None = None
    source_expr: str
    resolved_via: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class AnalysisLimits:
    max_source_files: int = 500
    max_doc_files: int = 200
    max_unchanged_source_files: int = 50
    time_budget_seconds: int = 60
    max_graph_depth: int = 3
    max_graph_nodes: int = 2000
    max_candidates_per_claim: int = 5
    include_full_entities: bool = False
    ai_review_max_items: int = 50

    @classmethod
    def from_settings(cls, settings: Any) -> "AnalysisLimits":
        return cls(
            max_source_files=settings.analysis_max_source_files,
            max_doc_files=settings.analysis_max_doc_files,
            max_unchanged_source_files=settings.analysis_max_unchanged_source_files,
            time_budget_seconds=settings.analysis_time_budget_seconds,
            max_graph_depth=settings.analysis_max_graph_depth,
            max_graph_nodes=settings.analysis_max_graph_nodes,
            max_candidates_per_claim=settings.analysis_max_candidates_per_claim,
            include_full_entities=settings.analysis_include_full_entities,
            ai_review_max_items=settings.ai_review_max_items,
        )


SkippedReason = Literal[
    "oversized",
    "binary",
    "not_utf8",
    "unsupported_language",
    "unsupported_doc_format",
    "syntax_error",
    "parse_error",
    "over_budget",
    "time_budget",
    "missing",
    "test_file",
    "other",
]


class SkippedAnalysisFile(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    side: Side
    reason: SkippedReason
    detail: str | None = None
