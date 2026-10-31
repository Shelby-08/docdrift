from collections.abc import Collection

from docsentry.intelligence.change_analysis.change_classifier import relevant_changes
from docsentry.intelligence.change_analysis.entity_matcher import match_entities
from docsentry.intelligence.change_analysis.semantic_diff import diff_entities
from docsentry.intelligence.drift.drift_detector import DriftResult, SideContext, detect_drift
from docsentry.intelligence.drift.rule_engine import evaluate_side
from docsentry.intelligence.models.common import Side
from docsentry.intelligence.models.findings import ConsistencyRecord
from tests.intelligence.side import BuiltSide, build_side

SHA_A = "a" * 40
SHA_B = "b" * 40


def ctx(built: BuiltSide, side: Side, sha: str, complete: bool = True) -> SideContext:
    return SideContext(
        side,
        sha,
        built.claims,
        built.entities,
        built.facts,
        built.relationships,
        built.index,
        complete,
    )


def analyze(
    base: dict[str, str],
    head: dict[str, str],
    changed_docs: Collection[str] = (),
    head_complete: bool = True,
    renames: dict[str, str] | None = None,
) -> DriftResult:
    b = build_side(base, SHA_A, Side.BASE)
    h = build_side(head, SHA_B, Side.HEAD)
    match = match_entities(b.entities, h.entities, renames or {})
    changes = relevant_changes(diff_entities(match))
    return detect_drift(
        ctx(b, Side.BASE, SHA_A),
        ctx(h, Side.HEAD, SHA_B, head_complete),
        changes,
        changed_doc_paths=changed_docs,
        file_renames=renames,
    )


def records(files: dict[str, str], rule: str | None = None) -> list[ConsistencyRecord]:
    built = build_side(files, SHA_B, Side.HEAD)
    recs = evaluate_side(
        Side.HEAD,
        built.claims,
        built.entities,
        built.facts,
        built.relationships,
        built.index,
        True,
        base_index=built.index,
    )
    return [r for r in recs.values() if rule is None or r.rule_id == rule]
