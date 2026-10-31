"""Documentation edges (DOCUMENTS, LINKS_TO) so the graph spans code and docs."""

from collections.abc import Collection, Sequence

from docsentry.intelligence.code_analysis.dependency_graph import DependencyGraph, Edge
from docsentry.intelligence.models.common import Provenance
from docsentry.intelligence.models.documentation import DocClaim, ParsedDocument
from docsentry.intelligence.models.relationships import Relationship


def add_documentation_edges(
    graph: DependencyGraph,
    relationships: Sequence[Relationship],
    claims: Sequence[DocClaim],
    parsed_docs: Sequence[ParsedDocument],
    paths: Collection[str],
) -> None:
    shas = {d.path: d.commit_sha for d in parsed_docs}
    by_id = {c.claim_id: c for c in claims}
    for rel in relationships:
        claim = by_id.get(rel.claim_id)
        if claim is None:
            continue
        prov = Provenance(
            path=claim.path,
            commit_sha=shas.get(claim.path, "0" * 40),
            line=claim.line,
            snippet=claim.original_text[:120],
        )
        targets = [rel.target_entity_id] if rel.target_entity_id else list(rel.alternatives)
        for target in targets:
            if target:
                graph.add_edge(
                    Edge(
                        src=claim.claim_id,
                        dst=target,
                        kind="DOCUMENTS",
                        resolved=not rel.ambiguous,
                        evidence=prov,
                    )
                )
    for doc in parsed_docs:
        for link in doc.links:
            if link.kind != "relative_path":
                continue
            resolved = link.resolved_path is not None and link.resolved_path in paths
            graph.add_edge(
                Edge(
                    src=doc.path,
                    dst=link.resolved_path or link.target,
                    kind="LINKS_TO",
                    resolved=resolved,
                    evidence=Provenance(
                        path=doc.path,
                        commit_sha=doc.commit_sha,
                        line=link.line,
                        snippet=link.text[:120],
                    ),
                )
            )
