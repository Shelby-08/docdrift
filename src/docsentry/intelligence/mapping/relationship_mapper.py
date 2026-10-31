"""Claim-to-entity relationship mapping for ONE side."""

import hashlib
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

from docsentry.intelligence.code_analysis.dependency_graph import DependencyGraph, Edge
from docsentry.intelligence.mapping.candidate_retriever import (
    build_candidate_index,
    retrieve_candidates,
)
from docsentry.intelligence.mapping.mapping_scorer import (
    ClaimContext,
    rank_of,
    score_entity,
    strength_of,
)
from docsentry.intelligence.models.code import CodeEntity
from docsentry.intelligence.models.common import AnalysisLimits, Side, Strength
from docsentry.intelligence.models.documentation import ClaimType, DocClaim, ParsedDocument
from docsentry.intelligence.models.relationships import (
    MappingSignal,
    Relationship,
    SignalKind,
)

_SKIP_TYPES = frozenset({ClaimType.VERSION_STATEMENT, ClaimType.HTTP_METHOD})
_VALUE_KINDS = frozenset({"constant", "config_key", "class_variable"})
_DEP_EDGES = frozenset({"CONFIGURES", "CALLS", "REFERENCES"})


@dataclass
class MappingOutcome:
    relationships: list[Relationship] = field(default_factory=list)
    truncated: bool = False


def _rid(side: Side, claim_id: str, target: str | None, alts: tuple[str, ...]) -> str:
    raw = "|".join([side.value, claim_id, target or "", ",".join(alts)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _build_contexts(
    claims: Sequence[DocClaim], parsed_docs: Sequence[ParsedDocument]
) -> dict[str, ClaimContext]:
    docs = {d.path: d for d in parsed_docs}
    stmt_block: dict[tuple[str, str], str] = {}
    block_text: dict[tuple[str, str], str] = {}
    for d in parsed_docs:
        for st in d.statements:
            stmt_block[(d.path, st.statement_id)] = st.block_id
        for b in d.blocks:
            block_text[(d.path, b.block_id)] = b.text
    out: dict[str, ClaimContext] = {}
    for c in claims:
        doc = docs.get(c.path)
        bid = stmt_block.get((c.path, c.statement_id))
        text = block_text.get((c.path, bid), "") if bid else ""
        links = tuple(lk for lk in (doc.links if doc else ()) if c.line <= lk.line <= c.end_line)
        out[c.claim_id] = ClaimContext(c, text, links, doc.commit_sha if doc else "0" * 40)
    return out


def map_claims_ex(
    claims: Sequence[DocClaim],
    entities: Sequence[CodeEntity],
    graph: DependencyGraph,
    parsed_docs: Sequence[ParsedDocument],
    side: Side = Side.HEAD,
    limits: AnalysisLimits | None = None,
) -> MappingOutcome:
    limits = limits or AnalysisLimits()
    index = build_candidate_index(entities)
    contexts = _build_contexts(claims, parsed_docs)
    outcome = MappingOutcome()

    for claim in sorted(claims, key=lambda c: (c.path, c.line, c.claim_id)):
        if claim.claim_type in _SKIP_TYPES:
            continue
        ctx = contexts[claim.claim_id]
        scored: list[tuple[CodeEntity, list[MappingSignal]]] = []
        for eid in retrieve_candidates(claim, index, limits):
            entity = index.entities[eid]
            signals = score_entity(ctx, entity)
            if signals:
                scored.append((entity, signals))
        if not scored:
            continue
        scored.sort(key=lambda t: (-rank_of(t[1]), t[0].symbol_key, t[0].id))
        top_rank, top_strength = rank_of(scored[0][1]), strength_of(scored[0][1])
        tied = [e for e, s in scored if rank_of(s) == top_rank and strength_of(s) == top_strength]
        if len(tied) > 1:
            alts = tuple(sorted(e.id for e in tied))
            outcome.relationships.append(
                Relationship(
                    relationship_id=_rid(side, claim.claim_id, None, alts),
                    side=side,
                    claim_id=claim.claim_id,
                    target_entity_id=None,
                    signals=tuple(scored[0][1]),
                    strength=top_strength,
                    rank_score=top_rank,
                    ambiguous=True,
                    alternatives=alts,
                    reasons=("ambiguous: equal top score among candidates",),
                )
            )
            continue

        direct_ids: set[str] = set()
        for entity, signals in scored:
            strength = strength_of(signals)
            reasons = [s.detail for s in signals]
            if strength == Strength.WEAK:
                reasons.append("weak_only")
            direct_ids.add(entity.id)
            outcome.relationships.append(
                Relationship(
                    relationship_id=_rid(side, claim.claim_id, entity.id, ()),
                    side=side,
                    claim_id=claim.claim_id,
                    target_entity_id=entity.id,
                    signals=tuple(signals),
                    strength=strength,
                    rank_score=rank_of(signals),
                    reasons=tuple(reasons),
                )
            )

        # E: dependency signal (never STRONG on its own)
        sources = [e for e, s in scored if strength_of(s) != Strength.WEAK][:3]
        for src in sources:
            found, trunc = _forward_dependencies(graph, src.id, limits)
            outcome.truncated = outcome.truncated or trunc
            for dep_id, path in found:
                dep = index.entities.get(dep_id)
                if dep is None or dep.kind not in _VALUE_KINDS or dep_id in direct_ids:
                    continue
                direct_ids.add(dep_id)
                signal = MappingSignal(
                    kind=SignalKind.DEPENDENCY,
                    tier=Strength.MEDIUM,
                    detail=f"{src.name} depends on {dep.name} via "
                    + "->".join(f"{e.kind}" for e in path),
                    evidence=path[0].evidence if path else None,
                )
                outcome.relationships.append(
                    Relationship(
                        relationship_id=_rid(side, claim.claim_id, dep_id, ()),
                        side=side,
                        claim_id=claim.claim_id,
                        target_entity_id=dep_id,
                        signals=(signal,),
                        strength=Strength.MEDIUM,
                        rank_score=rank_of([signal]),
                        reasons=(signal.detail, "dependency_only"),
                    )
                )
    return outcome


def _forward_dependencies(
    graph: DependencyGraph, start: str, limits: AnalysisLimits
) -> tuple[list[tuple[str, tuple[Edge, ...]]], bool]:
    found: list[tuple[str, tuple[Edge, ...]]] = []
    visited = {start}
    queue: deque[tuple[str, int, tuple[Edge, ...]]] = deque([(start, 0, ())])
    truncated = False
    while queue:
        node, depth, path = queue.popleft()
        for edge in graph.out_edges(node):
            if edge.kind not in _DEP_EDGES or not edge.resolved or edge.dst in visited:
                continue
            if depth >= limits.max_graph_depth:
                truncated = True
                continue
            if len(visited) >= limits.max_graph_nodes:
                return found, True
            visited.add(edge.dst)
            new_path = (*path, edge)
            found.append((edge.dst, new_path))
            queue.append((edge.dst, depth + 1, new_path))
    return found, truncated


def map_claims(
    claims: Sequence[DocClaim],
    entities: Sequence[CodeEntity],
    graph: DependencyGraph,
    parsed_docs: Sequence[ParsedDocument],
    side: Side = Side.HEAD,
    limits: AnalysisLimits | None = None,
) -> list[Relationship]:
    return map_claims_ex(claims, entities, graph, parsed_docs, side, limits).relationships
