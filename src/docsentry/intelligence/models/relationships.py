from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from docsentry.intelligence.models.common import Provenance, Side, Strength


class SignalKind(StrEnum):
    EXPLICIT_REFERENCE = "explicit_reference"
    EXACT_IDENTIFIER = "exact_identifier"
    HEADING_SYMBOL = "heading_symbol"
    CONFIG_OR_PARAMETER_NAME = "config_or_parameter_name"
    DEPENDENCY = "dependency"
    CONTEXTUAL = "contextual"
    FILE_PROXIMITY = "file_proximity"


class MappingSignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: SignalKind
    tier: Strength
    detail: str
    evidence: Provenance | None = None


class Relationship(BaseModel):
    """A claim-to-entity relationship hypothesis for ONE side.

    ``rank_score`` is used for ORDERING ONLY. It is not a probability and must never be
    compared across claims or used as evidence of correctness.
    """

    model_config = ConfigDict(frozen=True)

    relationship_id: str
    side: Side
    claim_id: str
    target_entity_id: str | None = None
    signals: tuple[MappingSignal, ...] = ()
    strength: Strength
    rank_score: float
    ambiguous: bool = False
    alternatives: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
