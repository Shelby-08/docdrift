from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from docsentry.intelligence.models.common import Certainty

BlockKind = Literal["heading", "paragraph", "table_row", "code_fence"]
LinkKind = Literal["relative_path", "anchor", "external", "other"]


class DocBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    block_id: str
    path: str
    kind: BlockKind
    container: tuple[str, ...] = ()
    text: str
    heading_path: tuple[str, ...] = ()
    line: int
    end_line: int
    token_type: str
    order: int


class DocStatement(BaseModel):
    model_config = ConfigDict(frozen=True)

    statement_id: str
    block_id: str
    path: str
    text: str
    raw_start: int
    raw_end: int
    line: int
    column: int
    end_line: int
    location_verified: bool
    heading_path: tuple[str, ...] = ()


class TableCellRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    row: int  # 0-based index
    col: int  # 0-based index
    text: str
    line: int  # 1-based source line
    line_verified: bool


class DocTable(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    header: tuple[str, ...]
    rows: tuple[tuple[TableCellRef, ...], ...]
    line: int


class CodeBlockRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    language: str | None = None
    line: int
    end_line: int
    identifiers: tuple[str, ...] = ()
    content_len: int


class DocLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    text: str
    target: str
    line: int
    kind: LinkKind
    resolved_path: str | None = None


class ClaimType(StrEnum):
    CONFIGURATION_DEFAULT = "configuration_default"
    API_SIGNATURE = "api_signature"
    CONFIGURATION_REFERENCE = "configuration_reference"
    IDENTIFIER_REFERENCE = "identifier_reference"
    PARAMETER_MENTION = "parameter_mention"
    HTTP_METHOD = "http_method"
    TYPE_MENTION = "type_mention"
    RETURN_TYPE = "return_type"
    VERSION_STATEMENT = "version_statement"
    BEHAVIORAL_CANDIDATE = "behavioral_candidate"


class DocClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_id: str
    claim_type: ClaimType
    subject: str | None = None
    subject_tokens: tuple[str, ...] = ()
    value: Any | None = None
    unit: str | None = None
    parameters: tuple[str, ...] = ()
    original_text: str
    path: str
    line: int
    column: int | None = None
    end_line: int
    statement_id: str
    heading_path: tuple[str, ...] = ()
    extraction_method: str
    certainty: Certainty
    location_verified: bool
    table_cell: tuple[int, int] | None = None


class ParsedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    commit_sha: str
    blocks: tuple[DocBlock, ...] = ()
    statements: tuple[DocStatement, ...] = ()
    tables: tuple[DocTable, ...] = ()
    code_blocks: tuple[CodeBlockRef, ...] = ()
    links: tuple[DocLink, ...] = ()
    claims: tuple[DocClaim, ...] = ()
    errors: tuple[str, ...] = ()
