from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from docsentry.intelligence.models.common import (
    ConsistencyState,
    Exposure,
    JsonValue,
    Provenance,
    Side,
)
from docsentry.intelligence.models.documentation import DocClaim


class Category(StrEnum):
    DEFAULT_VALUE_MISMATCH = "default_value_mismatch"
    REMOVED_PARAMETER = "removed_parameter"
    RENAMED_OR_REMOVED_CONFIG_KEY = "renamed_or_removed_config_key"
    RENAMED_OR_REMOVED_SYMBOL = "renamed_or_removed_symbol"
    TYPE_CONTRACT = "type_contract"
    BEHAVIORAL_CONFIG = "behavioral_config"


class EvidenceStatus(StrEnum):
    CONFIRMED = "confirmed"
    POTENTIAL = "potential"
    AMBIGUOUS_RELATIONSHIP = "ambiguous_relationship"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class TemporalStatus(StrEnum):
    NEWLY_INTRODUCED = "newly_introduced"
    PRE_EXISTING = "pre_existing"
    RESOLVED = "resolved"
    INDETERMINATE = "indeterminate"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["code_fact", "doc_claim", "mapping_signal", "change", "temporal"]
    side: Side | None = None
    description: str
    provenance: Provenance | None = None


class DriftFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding_id: str
    rule_id: str
    category: Category
    evidence_status: EvidenceStatus
    temporal_status: TemporalStatus
    severity: Severity
    description: str
    documentation_file: str
    documentation_line: int | None = None
    affected_text: str = Field(max_length=500)
    code_file: str | None = None
    code_line: int | None = None
    old_value: JsonValue | None = None
    new_value: JsonValue | None = None
    suggested_correction: str | None = None
    evidence: tuple[Evidence, ...] = ()
    mapping_reasons: tuple[str, ...] = ()
    requires_ai_review: bool = False
    introduced_by_current_pr: bool | None = None
    key: str


class ConsistencyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    rule_id: str
    category: Category
    state: ConsistencyState
    evidence_status: EvidenceStatus
    claim: DocClaim
    entity_id: str | None = None
    entity_name: str | None = None
    property: str
    doc_value: JsonValue | None = None
    code_value: JsonValue | None = None
    summary: str = ""
    reasons: tuple[str, ...] = ()
    mapping_reasons: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    code_provenance: Provenance | None = None
    exposure: Exposure = Exposure.UNKNOWN
    suggested_correction: str | None = None
    requires_ai_review: bool = False
