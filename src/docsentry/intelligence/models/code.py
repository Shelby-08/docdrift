from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from docsentry.intelligence.models.common import Exposure, JsonValue, Provenance, ValueRepr

ParameterKind = Literal[
    "positional_only",
    "positional_or_keyword",
    "var_positional",
    "keyword_only",
    "var_keyword",
]


class Parameter(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    kind: ParameterKind
    default: ValueRepr | None = None
    annotation: str | None = None


EntityKind = Literal[
    "function",
    "method",
    "class",
    "constant",
    "class_variable",
    "config_key",
]


class CodeEntity(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    symbol_key: str
    kind: EntityKind
    name: str
    qualname: str
    path: str
    container_id: str | None = None
    exposure: Exposure
    conditional: bool = False
    decorators: tuple[str, ...] = ()
    docstring_summary: str | None = Field(default=None, max_length=200)
    provenance: Provenance
    parameters: tuple[Parameter, ...] = ()
    return_annotation: str | None = None
    is_async: bool = False
    bases: tuple[str, ...] = ()
    value: ValueRepr | None = None
    annotation: str | None = None
    alias_target: str | None = None


class FactType(StrEnum):
    FUNCTION_SIGNATURE = "function_signature"
    PARAMETER_DEFAULT = "parameter_default"
    PARAMETER_TYPE = "parameter_type"
    RETURN_TYPE = "return_type"
    CONSTANT_VALUE = "constant_value"
    CONFIG_DEFAULT = "config_default"
    CLASS_STRUCTURE = "class_structure"
    IMPORT_DEPENDENCY = "import_dependency"
    CALL_ARGUMENT = "call_argument"


class CodeFact(BaseModel):
    model_config = ConfigDict(frozen=True)
    fact_id: str
    fact_type: FactType
    entity_id: str
    entity_name: str
    property: str | None = None
    value: JsonValue | None = None
    resolved: bool = True
    unit_hint: str | None = None
    provenance: Provenance
    details: dict[str, Any] = Field(default_factory=dict)


class ImportRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    module: str | None = None
    name: str | None = None
    alias: str | None = None
    level: int = 0
    resolved_path: str | None = None
    provenance: Provenance


class ReferenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    name: str
    kind: Literal["call", "name"]
    enclosing_entity_id: str | None = None
    resolved_entity_id: str | None = None
    resolved: bool = False
    provenance: Provenance


class StringKeyReference(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    value: str
    provenance: Provenance


class ParsedSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: str
    commit_sha: str
    language: str = "python"
    entities: tuple[CodeEntity, ...] = ()
    facts: tuple[CodeFact, ...] = ()
    imports: tuple[ImportRecord, ...] = ()
    references: tuple[ReferenceRecord, ...] = ()
    string_keys: tuple[StringKeyReference, ...] = ()
    all_names: tuple[str, ...] | None = None
    has_module_getattr: bool = False
    errors: tuple[str, ...] = ()
