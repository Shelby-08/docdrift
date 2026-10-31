"""Strict validation of model output against the packets that were actually sent."""

import json

from pydantic import ValidationError

from docsentry.ai_review.evidence import Packet
from docsentry.ai_review.models import AIItemAssessment, AIReviewBatchOutput, AIVerdict


class ValidationFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_batch(raw: str, batch: list[Packet]) -> tuple[AIItemAssessment, ...]:
    """Return validated assessments (may be fewer than items). Raises ValidationFailure."""
    try:
        out = AIReviewBatchOutput.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        raise ValidationFailure("ai_schema_invalid") from None
    by_id = {p.item_id: p for p in batch}
    seen: set[str] = set()
    result: list[AIItemAssessment] = []
    for a in out.assessments:
        pk = by_id.get(a.item_id)
        if pk is None or a.item_id in seen:
            raise ValidationFailure("ai_reference_invalid")
        seen.add(a.item_id)
        if any(e not in pk.evidence_ids for e in a.evidence_ids):
            raise ValidationFailure("ai_reference_invalid")
        if a.suggested_target_id is not None and (
            pk.kind != "ambiguous_relationship" or a.suggested_target_id not in pk.candidate_ids
        ):
            raise ValidationFailure("ai_reference_invalid")
        if (
            a.verdict in (AIVerdict.SUPPORTS_DRIFT, AIVerdict.LIKELY_CONSISTENT)
            and not a.evidence_ids
        ):
            a = a.model_copy(update={"verdict": AIVerdict.UNCERTAIN})
        result.append(a)
    return tuple(result)
