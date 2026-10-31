from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from docsentry.intelligence.models.common import Exposure, JsonValue, Provenance, Strength


class ChangeType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    RENAMED = "renamed"
    MOVED = "moved"


class ChangedProperty(StrEnum):
    ENTITY = "entity"
    DEFAULT_VALUE = "default_value"
    PARAMETER_ADDED = "parameter_added"
    PARAMETER_REMOVED = "parameter_removed"
    PARAMETER_TYPE = "parameter_type"
    RETURN_TYPE = "return_type"
    CONSTANT_VALUE = "constant_value"
    EXPOSURE = "exposure"
    CONFIG_DEFAULT = "config_default"
    SIGNATURE_OTHER = "signature_other"


class SemanticChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_id: str
    entity_id: str
    base_entity_id: str | None = None
    symbol_key: str
    base_symbol_key: str | None = None
    entity_name: str
    change_type: ChangeType
    property: ChangedProperty
    detail: str | None = None
    before: JsonValue | None = None
    after: JsonValue | None = None
    base_provenance: Provenance | None = None
    head_provenance: Provenance | None = None
    evidence: tuple[str, ...] = ()
    rename_confidence: Strength | None = None
    exposure: Exposure = Exposure.UNKNOWN
    low_relevance: bool = False
