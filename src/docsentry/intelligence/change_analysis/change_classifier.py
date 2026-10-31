from collections.abc import Sequence

from docsentry.intelligence.models.changes import SemanticChange
from docsentry.intelligence.models.common import Exposure


def relevant_changes(changes: Sequence[SemanticChange]) -> list[SemanticChange]:
    """Keep every change; flag private-entity changes as low relevance (never dropped)."""
    out: list[SemanticChange] = []
    for c in changes:
        if c.exposure == Exposure.PRIVATE and not c.low_relevance:
            out.append(c.model_copy(update={"low_relevance": True}))
        else:
            out.append(c)
    return out
