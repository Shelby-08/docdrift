from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

SymbolKind = Literal["function", "async_function", "class", "method", "variable"]
ChangeKind = Literal["added", "removed", "signature_changed", "docstring_changed", "body_changed"]
DocBlockKind = Literal["paragraph", "code_block", "heading", "list_item", "table"]
ClaimKind = Literal["symbol_mention", "signature_quote", "behavior_claim"]
DriftCategory = Literal["stale_reference", "broken_contract", "undocumented_change", "behavioral_drift"]
DriftSeverity = Literal["critical", "warning", "info"]


class ParameterInfo(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    type_annotation: str | None = None
    default_value: str | None = None
    kind: Literal["positional_only", "positional_or_keyword", "var_positional", "keyword_only", "var_keyword"] = "positional_or_keyword"


class SymbolSignature(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    qualified_name: str
    kind: SymbolKind
    parameters: list[ParameterInfo] = Field(default_factory=list)
    return_type: str | None = None
    docstring: str | None = None
    line_start: int
    line_end: int
    decorators: list[str] = Field(default_factory=list)


class SymbolChange(BaseModel):
    model_config = ConfigDict(frozen=True)
    file_path: str
    symbol_name: str
    qualified_name: str
    change_kind: ChangeKind
    before: SymbolSignature | None = None
    after: SymbolSignature | None = None
    breaking: bool = False
    details: str = ""


class DocBlock(BaseModel):
    model_config = ConfigDict(frozen=True)
    file_path: str
    block_kind: DocBlockKind
    heading_context: str | None = None
    line_start: int
    line_end: int
    content: str


class ExtractedClaim(BaseModel):
    model_config = ConfigDict(frozen=True)
    file_path: str
    line_number: int
    claim_kind: ClaimKind
    target_symbol: str
    extracted_text: str
    context: str | None = None


class CodeDocMapping(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_file: str
    doc_file: str
    matched_symbol: str
    confidence: float = Field(ge=0.0, le=1.0)
    method: Literal["explicit_mention", "file_proximity", "heading_match"]


class DriftFinding(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    category: DriftCategory
    severity: DriftSeverity
    title: str
    explanation: str
    remediation: str
    source_file: str
    doc_file: str | None = None
    symbol_name: str | None = None
    line_number: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class DriftAnalysisReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    findings: list[DriftFinding] = Field(default_factory=list)
    symbol_changes: list[SymbolChange] = Field(default_factory=list)
    extracted_claims: list[ExtractedClaim] = Field(default_factory=list)
    mappings: list[CodeDocMapping] = Field(default_factory=list)
    summary: str
    critical_count: int = 0
    warning_count: int = 0
    info_count: int = 0
