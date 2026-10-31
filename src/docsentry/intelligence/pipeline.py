"""Pure analysis pipeline: RepoSnapshots in, AnalysisResult out."""

import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from docsentry.config import Settings
from docsentry.intelligence.change_analysis.change_classifier import relevant_changes
from docsentry.intelligence.change_analysis.entity_matcher import match_entities
from docsentry.intelligence.change_analysis.semantic_diff import diff_entities
from docsentry.intelligence.code_analysis.dependency_graph import (
    DependencyGraph,
    build_dependency_graph,
)
from docsentry.intelligence.code_analysis.language_registry import get_adapter
from docsentry.intelligence.code_analysis.symbol_index import SymbolIndex, resolve_value_references
from docsentry.intelligence.documentation.claim_extractor import extract_claims
from docsentry.intelligence.documentation.markdown_parser import parse_markdown
from docsentry.intelligence.drift.drift_detector import SideContext, detect_drift
from docsentry.intelligence.mapping.doc_graph import add_documentation_edges
from docsentry.intelligence.mapping.relationship_mapper import map_claims_ex
from docsentry.intelligence.models.analysis import (
    AIReviewInput,
    AIReviewItem,
    AnalysisContext,
    AnalysisResult,
    IndexedFile,
)
from docsentry.intelligence.models.changes import SemanticChange
from docsentry.intelligence.models.code import CodeEntity, CodeFact, ParsedSource
from docsentry.intelligence.models.common import (
    AnalysisLimits,
    FileClass,
    Side,
    SkippedAnalysisFile,
)
from docsentry.intelligence.models.documentation import ClaimType, DocClaim, ParsedDocument
from docsentry.intelligence.models.findings import DriftFinding, EvidenceStatus, Severity
from docsentry.intelligence.models.relationships import Relationship, SignalKind
from docsentry.intelligence.repository.file_classifier import classify_file
from docsentry.intelligence.repository.loader import FileSource, load_snapshots
from docsentry.intelligence.repository.snapshot import RepoSnapshot
from docsentry.retrieval.models import PullRequestBundle

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2, Severity.INFO: 3}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _Budget:
    def __init__(self, monotonic: Callable[[], float], started: float, seconds: int) -> None:
        self.monotonic = monotonic
        self.started = started
        self.seconds = seconds
        self.hit = False

    def exceeded(self) -> bool:
        if self.monotonic() - self.started > self.seconds:
            self.hit = True
        return self.hit


class _SideAnalysis:
    def __init__(self, side: Side, snap: RepoSnapshot) -> None:
        self.side = side
        self.snap = snap
        self.sources: tuple[ParsedSource, ...] = ()
        self.docs: list[ParsedDocument] = []
        self.claims: list[DocClaim] = []
        self.index: SymbolIndex = SymbolIndex([], [])
        self.graph = DependencyGraph()
        self.relationships: list[Relationship] = []
        self.entities: list[CodeEntity] = []
        self.facts: list[CodeFact] = []
        self.indexed_sources: list[IndexedFile] = []
        self.indexed_docs: list[IndexedFile] = []
        self.skipped: list[SkippedAnalysisFile] = []
        self.parse_errors: list[str] = []
        self.truncated = False
        self.warnings: list[str] = []


def _parse_side(
    sa: _SideAnalysis,
    limits: AnalysisLimits,
    budget: _Budget,
    cache: dict[tuple[str, str], ParsedSource],
) -> None:
    snap = sa.snap
    parsed: list[ParsedSource] = []
    n_src = 0
    for path in sorted(snap.files):
        cls = classify_file(path)
        if cls != FileClass.SOURCE:
            continue
        adapter = get_adapter(path)
        if adapter is None:
            continue
        if n_src >= limits.max_source_files:
            sa.skipped.append(SkippedAnalysisFile(path=path, side=sa.side, reason="over_budget"))
            continue
        if budget.exceeded():
            sa.skipped.append(SkippedAnalysisFile(path=path, side=sa.side, reason="time_budget"))
            continue
        n_src += 1
        key = (snap.commit_sha, path)
        ps = cache.get(key)
        if ps is None:
            try:
                ps = adapter.parse(path, snap.files[path], snap.commit_sha)
            except Exception as exc:  # parser must never take the pipeline down
                sa.parse_errors.append(f"{path}: {type(exc).__name__}")
                sa.skipped.append(
                    SkippedAnalysisFile(path=path, side=sa.side, reason="parse_error")
                )
                sa.indexed_sources.append(
                    IndexedFile(path=path, side=sa.side, file_class=cls, language="python")
                )
                continue
            cache[key] = ps
        ok = not ps.errors
        if not ok:
            sa.parse_errors.extend(f"{path}: {e}" for e in ps.errors)
            sa.skipped.append(
                SkippedAnalysisFile(
                    path=path, side=sa.side, reason="syntax_error", detail=ps.errors[0][:200]
                )
            )
        sa.indexed_sources.append(
            IndexedFile(path=path, side=sa.side, file_class=cls, language="python", parsed=ok)
        )
        parsed.append(ps)
    index = SymbolIndex(parsed, sorted(snap.paths))
    resolved = resolve_value_references(parsed, index)
    sa.sources = tuple(resolved)
    sa.index = SymbolIndex(resolved, sorted(snap.paths))
    sa.graph = build_dependency_graph(resolved, sa.index)
    sa.entities = [e for s in resolved for e in s.entities]
    sa.facts = [f for s in resolved for f in s.facts]

    n_docs = 0
    for path in sorted(snap.files):
        if classify_file(path) != FileClass.DOC:
            continue
        if n_docs >= limits.max_doc_files:
            sa.skipped.append(SkippedAnalysisFile(path=path, side=sa.side, reason="over_budget"))
            continue
        if budget.exceeded():
            sa.skipped.append(SkippedAnalysisFile(path=path, side=sa.side, reason="time_budget"))
            continue
        n_docs += 1
        doc = parse_markdown(path, snap.files[path], snap.commit_sha)
        sa.docs.append(doc)
        sa.claims.extend(extract_claims(doc))
        sa.indexed_docs.append(
            IndexedFile(
                path=path, side=sa.side, file_class=FileClass.DOC, language="markdown", parsed=True
            )
        )
        for err in doc.errors:
            if err != "front_matter_skipped":
                sa.parse_errors.append(f"{path}: {err}")


def _map_side(sa: _SideAnalysis, limits: AnalysisLimits) -> None:
    outcome = map_claims_ex(sa.claims, sa.entities, sa.graph, sa.docs, sa.side, limits)
    sa.relationships = outcome.relationships
    sa.truncated = outcome.truncated
    add_documentation_edges(sa.graph, sa.relationships, sa.claims, sa.docs, sa.snap.paths)


def _unsupported(sa: _SideAnalysis) -> None:
    for path in sorted(sa.snap.paths):
        cls = classify_file(path)
        if cls == FileClass.UNSUPPORTED:
            reason = (
                "unsupported_doc_format"
                if path.lower().endswith((".mdx", ".rst", ".adoc", ".asciidoc"))
                else "unsupported_language"
            )
            sa.skipped.append(SkippedAnalysisFile(path=path, side=sa.side, reason=reason))


def _changed_doc_paths(
    base: RepoSnapshot, head: RepoSnapshot, file_renames: Mapping[str, str]
) -> set[str]:
    inverse = {v: k for k, v in file_renames.items()}
    out: set[str] = set()
    for path, text in head.files.items():
        if classify_file(path) != FileClass.DOC:
            continue
        base_text = base.files.get(inverse.get(path, path))
        if base_text is None or base_text != text:
            out.add(path)
    return out


def analyze_repositories(
    base: RepoSnapshot,
    head: RepoSnapshot,
    ctx: AnalysisContext,
    limits: AnalysisLimits,
    clock: Callable[[], datetime] = _utcnow,
    file_renames: Mapping[str, str] | None = None,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    started: float | None = None,
) -> AnalysisResult:
    renames = dict(file_renames or {})
    budget = _Budget(
        monotonic, monotonic() if started is None else started, limits.time_budget_seconds
    )
    cache: dict[tuple[str, str], ParsedSource] = {}
    sides = {Side.BASE: _SideAnalysis(Side.BASE, base), Side.HEAD: _SideAnalysis(Side.HEAD, head)}
    for sa in sides.values():
        _parse_side(sa, limits, budget, cache)
        _unsupported(sa)
        _map_side(sa, limits)
    b, h = sides[Side.BASE], sides[Side.HEAD]

    match = match_entities(b.entities, h.entities, renames)
    changes = relevant_changes(diff_entities(match))
    changed_docs = _changed_doc_paths(base, head, renames)

    def side_ctx(sa: _SideAnalysis) -> SideContext:
        return SideContext(
            sa.side,
            sa.snap.commit_sha,
            sa.claims,
            sa.entities,
            sa.facts,
            sa.relationships,
            sa.index,
            sa.snap.source_scan_complete and not budget.hit,
        )

    drift = detect_drift(
        side_ctx(b), side_ctx(h), changes, changed_doc_paths=changed_docs, file_renames=renames
    )
    findings = tuple(drift.findings)

    skipped_all = {
        (s.path, s.side.value, s.reason): s
        for s in [*base.skipped, *head.skipped, *b.skipped, *h.skipped]
    }
    skipped = tuple(sorted(skipped_all.values(), key=lambda s: (s.path, s.side.value, s.reason)))

    reasons: list[str] = []
    for label, snap in (("base", base), ("head", head)):
        reasons.extend(f"{label}:{r}" for r in snap.incomplete_reasons)
    counted_skips = [s for s in skipped if s.reason != "test_file"]
    if counted_skips:
        reasons.append(f"skipped_files:{len(counted_skips)}")
    warnings: list[str] = []
    if budget.hit:
        reasons.append("time_budget")
        warnings.append("time budget exceeded; analysis is partial")
    if b.truncated or h.truncated:
        reasons.append("graph_traversal_truncated")
    if b.parse_errors or h.parse_errors:
        reasons.append("parse_errors")
    reasons = list(dict.fromkeys(reasons))

    ai_input = _build_ai_input(h, findings, changes, changed_docs, limits, complete=not reasons)

    stats: dict[str, Any] = {
        "findings": len(findings),
        "claims": {"base": len(b.claims), "head": len(h.claims)},
        "relationships": {"base": len(b.relationships), "head": len(h.relationships)},
        "semantic_changes": len(changes),
        "skipped_by_reason": dict(sorted(Counter(s.reason for s in skipped).items())),
        "changed_doc_files": len(changed_docs),
        **drift.stats,
    }
    parse_errors = tuple(sorted({*b.parse_errors, *h.parse_errors}))
    return AnalysisResult(
        context=ctx,
        generated_at=clock(),
        complete=not reasons,
        incomplete_reasons=tuple(reasons),
        indexed_source_files=tuple(
            sorted([*b.indexed_sources, *h.indexed_sources], key=lambda f: (f.path, f.side.value))
        ),
        indexed_doc_files=tuple(
            sorted([*b.indexed_docs, *h.indexed_docs], key=lambda f: (f.path, f.side.value))
        ),
        entities_count={"base": len(b.entities), "head": len(h.entities)},
        entities=tuple(h.entities) if limits.include_full_entities else (),
        facts=tuple(h.facts),
        claims=tuple(h.claims),
        relationships=tuple(h.relationships),
        semantic_changes=tuple(changes),
        findings=findings,
        skipped_files=skipped,
        warnings=tuple(warnings),
        parse_errors=parse_errors,
        stats=stats,
        ai_review_input=ai_input,
    )


def _build_ai_input(
    h: _SideAnalysis,
    findings: Sequence[DriftFinding],
    changes: Sequence[SemanticChange],
    changed_docs: set[str],
    limits: AnalysisLimits,
    *,
    complete: bool,
) -> AIReviewInput:
    by_claim = {c.claim_id: c for c in h.claims}
    by_entity = {e.id: e for e in h.entities}
    changed_entity_ids = {c.entity_id for c in changes}
    items: list[tuple[tuple[int, int, str], AIReviewItem]] = []

    def loc(e: CodeEntity) -> str:
        return f"{e.provenance.path}:{e.provenance.line}"

    for f in findings:
        if not f.requires_ai_review:
            continue
        pri = (0, _SEVERITY_ORDER[f.severity], f.finding_id)
        items.append(
            (
                pri,
                AIReviewItem(
                    item_id=f"finding:{f.finding_id}",
                    kind="finding",
                    claim_text=f.affected_text[:500],
                    doc_path=f.documentation_file,
                    doc_line=f.documentation_line,
                    code_facts=tuple(
                        e.description[:200] for e in f.evidence if e.kind == "code_fact"
                    )[:5],
                    code_locations=((f"{f.code_file}:{f.code_line}",) if f.code_file else ()),
                    relationship_summary="; ".join(f.mapping_reasons)[:300],
                    ambiguity_reasons=tuple(
                        r for r in f.mapping_reasons if "ambiguous" in r or "insufficient" in r
                    ),
                    temporal_status=f.temporal_status.value,
                    deterministic_finding_id=f.finding_id,
                ),
            )
        )
    for r in h.relationships:
        claim = by_claim.get(r.claim_id)
        if claim is None:
            continue
        targets = [r.target_entity_id] if r.target_entity_id else list(r.alternatives)
        relevant = claim.path in changed_docs or any(t in changed_entity_ids for t in targets if t)
        if not relevant:
            continue
        ents = [by_entity[t] for t in targets if t in by_entity]
        dep_only = {s.kind for s in r.signals} == {SignalKind.DEPENDENCY}
        if r.ambiguous:
            kind = "ambiguous_relationship"
            pri = (1, 0, r.relationship_id)
        elif dep_only:
            kind = "indirect_dependency"
            pri = (2, 0, r.relationship_id)
        else:
            continue
        items.append(
            (
                pri,
                AIReviewItem(
                    item_id=f"{kind}:{r.relationship_id}",
                    kind=kind,
                    claim_text=claim.original_text[:500],
                    doc_path=claim.path,
                    doc_line=claim.line,
                    code_facts=tuple(f"{e.kind} {e.qualname}" for e in ents)[:5],
                    code_locations=tuple(loc(e) for e in ents)[:5],
                    relationship_summary="; ".join(r.reasons)[:300],
                    ambiguity_reasons=r.reasons if r.ambiguous else (),
                ),
            )
        )
    for c in h.claims:
        if c.claim_type != ClaimType.BEHAVIORAL_CANDIDATE:
            continue
        rel_targets = {
            r.target_entity_id
            for r in h.relationships
            if r.claim_id == c.claim_id and r.target_entity_id
        }
        if c.path not in changed_docs and not (rel_targets & changed_entity_ids):
            continue
        ents = [by_entity[t] for t in sorted(rel_targets) if t in by_entity]
        items.append(
            (
                (3, 0, c.claim_id),
                AIReviewItem(
                    item_id=f"behavioral_candidate:{c.claim_id}",
                    kind="behavioral_candidate",
                    claim_text=c.original_text[:500],
                    doc_path=c.path,
                    doc_line=c.line,
                    code_facts=tuple(f"{e.kind} {e.qualname}" for e in ents)[:5],
                    code_locations=tuple(loc(e) for e in ents)[:5],
                ),
            )
        )
    items.sort(key=lambda t: t[0])
    seen: set[str] = set()
    unique: list[AIReviewItem] = []
    for _, item in items:
        if item.item_id not in seen:
            seen.add(item.item_id)
            unique.append(item)
    kept = unique[: limits.ai_review_max_items]
    return AIReviewInput(
        items=tuple(kept),
        omitted_count=len(unique) - len(kept),
        complete=complete and len(unique) == len(kept),
    )


def analyze_bundle(
    bundle: PullRequestBundle,
    source: FileSource,
    settings: Settings,
    log: logging.Logger | None = None,
    *,
    clock: Callable[[], datetime] = _utcnow,
    monotonic: Callable[[], float] = time.monotonic,
) -> AnalysisResult:
    log = log or logger
    limits = AnalysisLimits.from_settings(settings)
    started = monotonic()
    base, head = load_snapshots(bundle, source, limits, monotonic, started)
    renames = {
        cf.previous_filename: cf.filename for cf in bundle.changed_files if cf.previous_filename
    }
    c = bundle.context
    ctx = AnalysisContext(
        owner=c.owner,
        repository=c.repository,
        repository_id=c.repository_id,
        pull_number=c.pull_number,
        base_sha=base.commit_sha,
        head_sha=head.commit_sha,
        original_base_sha=c.base_sha,
        delivery_id=c.delivery_id,
    )
    result = analyze_repositories(
        base, head, ctx, limits, clock, renames, monotonic=monotonic, started=started
    )
    log.info(
        "analysis_complete",
        extra={
            "pull_number": c.pull_number,
            "head_sha": head.commit_sha,
            "findings": len(result.findings),
            "claims": len(result.claims),
            "skipped": len(result.skipped_files),
            "complete": result.complete,
        },
    )
    return result


__all__ = ["EvidenceStatus", "analyze_bundle", "analyze_repositories"]
