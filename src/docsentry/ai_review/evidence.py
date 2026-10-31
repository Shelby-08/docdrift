"""Pure, bounded evidence packets built from Stage 3 output only."""

import json
from dataclasses import dataclass, field
from typing import Any

from docsentry.ai_review.models import AIEvidenceRef
from docsentry.intelligence.models.analysis import AIReviewItem, AnalysisResult

MAX_FACTS = 4
TEXT = 500


@dataclass(frozen=True)
class Packet:
    item_id: str
    kind: str
    data: dict[str, Any]
    evidence_ids: frozenset[str]
    candidate_ids: frozenset[str] = field(default_factory=frozenset)

    def size(self) -> int:
        return len(json.dumps(self.data, ensure_ascii=False))


def _candidates(res: AnalysisResult, item: AIReviewItem) -> tuple[str, ...]:
    if item.kind != "ambiguous_relationship":
        return ()
    rid = item.item_id.split(":", 1)[-1]
    for r in res.relationships:
        if r.relationship_id == rid:
            ids = [r.target_entity_id] if r.target_entity_id else []
            return tuple(dict.fromkeys([*ids, *r.alternatives]))[:5]
    return ()


def build_packet(res: AnalysisResult, item: AIReviewItem, facts: int = MAX_FACTS) -> Packet:
    refs: list[AIEvidenceRef] = [
        AIEvidenceRef(
            evidence_id="E1", kind="doc_claim", location=f"{item.doc_path}:{item.doc_line}"
        )
    ]
    ev: list[dict[str, str]] = [{"id": "E1", "kind": "doc_claim", "text": item.claim_text[:TEXT]}]
    for i, fact in enumerate(item.code_facts[:facts]):
        eid = f"E{i + 2}"
        loc = item.code_locations[i] if i < len(item.code_locations) else ""
        refs.append(AIEvidenceRef(evidence_id=eid, kind="code_fact", location=loc))
        ev.append({"id": eid, "kind": "code_fact", "text": fact[:200], "location": loc[:200]})
    cands = _candidates(res, item)
    data: dict[str, Any] = {
        "item_id": item.item_id,
        "kind": item.kind,
        "doc_location": f"{item.doc_path}:{item.doc_line}",
        "evidence": ev,
        "relationship_summary": item.relationship_summary[:300],
        "ambiguity_reasons": [r[:200] for r in item.ambiguity_reasons[:3]],
        "temporal_status": item.temporal_status,
        "candidate_ids": list(cands),
    }
    return Packet(
        item.item_id, item.kind, data, frozenset(r.evidence_id for r in refs), frozenset(cands)
    )


def build_batches(
    res: AnalysisResult, max_items: int, max_chars: int, overhead: int = 1500
) -> tuple[list[list[Packet]], int]:
    """Batch packets in Stage 3 order. Returns (batches, count_of_unbatchable_items)."""
    batches: list[list[Packet]] = []
    cur: list[Packet] = []
    size = overhead
    dropped = 0
    for item in res.ai_review_input.items:
        pk = build_packet(res, item)
        if pk.size() + overhead > max_chars:
            pk = build_packet(res, item, facts=1)
        if pk.size() + overhead > max_chars:
            dropped += 1
            continue
        if cur and (len(cur) >= max_items or size + pk.size() > max_chars):
            batches.append(cur)
            cur, size = [], overhead
        cur.append(pk)
        size += pk.size()
    if cur:
        batches.append(cur)
    return batches, dropped
