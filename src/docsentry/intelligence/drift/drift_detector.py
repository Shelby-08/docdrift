"""Orchestrates both-side rule evaluation and temporal classification."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from docsentry.intelligence.code_analysis.symbol_index import SymbolIndex
from docsentry.intelligence.drift.consistency_checker import classify_temporal_ex
from docsentry.intelligence.drift.rule_engine import evaluate_side
from docsentry.intelligence.models.changes import ChangeType, SemanticChange
from docsentry.intelligence.models.code import CodeEntity, CodeFact
from docsentry.intelligence.models.common import Side
from docsentry.intelligence.models.documentation import DocClaim
from docsentry.intelligence.models.findings import ConsistencyRecord, DriftFinding
from docsentry.intelligence.models.relationships import Relationship


@dataclass
class SideContext:
    side: Side
    commit_sha: str
    claims: Sequence[DocClaim]
    entities: Sequence[CodeEntity]
    facts: Sequence[CodeFact]
    relationships: Sequence[Relationship]
    symbol_index: SymbolIndex
    snapshot_complete: bool = True


@dataclass
class DriftResult:
    findings: list[DriftFinding] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)
    base_records: dict[str, ConsistencyRecord] = field(default_factory=dict)
    head_records: dict[str, ConsistencyRecord] = field(default_factory=dict)


def detect_drift(
    base_ctx: SideContext,
    head_ctx: SideContext,
    changes: Sequence[SemanticChange],
    *,
    changed_doc_paths: Collection[str] = (),
    file_renames: Mapping[str, str] | None = None,
) -> DriftResult:
    renames = dict(file_renames or {})
    key_map = {
        c.base_symbol_key: c.symbol_key
        for c in changes
        if c.change_type == ChangeType.RENAMED and c.base_symbol_key
    }
    name_map = {
        str(c.before): str(c.after)
        for c in changes
        if c.change_type == ChangeType.RENAMED and c.before and c.after
    }

    def base_key(e: CodeEntity) -> str:
        mapped = key_map.get(e.symbol_key)
        if mapped:
            return mapped
        return f"{renames.get(e.path, e.path)}::{e.qualname}"

    def base_doc(path: str) -> str:
        return renames.get(path, path)

    base_records = evaluate_side(
        Side.BASE,
        base_ctx.claims,
        base_ctx.entities,
        base_ctx.facts,
        base_ctx.relationships,
        base_ctx.symbol_index,
        base_ctx.snapshot_complete,
        doc_sha=base_ctx.commit_sha,
        entity_key=base_key,
        doc_path=base_doc,
    )
    head_records = evaluate_side(
        Side.HEAD,
        head_ctx.claims,
        head_ctx.entities,
        head_ctx.facts,
        head_ctx.relationships,
        head_ctx.symbol_index,
        head_ctx.snapshot_complete,
        doc_sha=head_ctx.commit_sha,
        base_index=base_ctx.symbol_index,
        rename_candidates=name_map,
    )
    changed_docs = set(changed_doc_paths)

    def touched(key: str) -> bool:
        b, h = base_records.get(key), head_records.get(key)
        if b is None or h is None:
            return True
        if b.claim.original_text != h.claim.original_text or b.doc_value != h.doc_value:
            return True
        if b.code_value != h.code_value:
            return True
        return b.claim.path in changed_docs or h.claim.path in changed_docs

    findings, stats = classify_temporal_ex(base_records, head_records, touched)
    findings.sort(key=lambda f: (f.documentation_file, f.documentation_line or 0, f.rule_id, f.key))
    return DriftResult(findings, stats.as_dict(), base_records, head_records)
