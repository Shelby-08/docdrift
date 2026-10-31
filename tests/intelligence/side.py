"""Test helper: build one analysed side from in-memory files (mirrors the pipeline)."""

from dataclasses import dataclass

from docsentry.intelligence.code_analysis.dependency_graph import (
    DependencyGraph,
    build_dependency_graph,
)
from docsentry.intelligence.code_analysis.python_parser import parse_python
from docsentry.intelligence.code_analysis.symbol_index import SymbolIndex, resolve_value_references
from docsentry.intelligence.documentation.claim_extractor import extract_claims
from docsentry.intelligence.documentation.markdown_parser import parse_markdown
from docsentry.intelligence.mapping.doc_graph import add_documentation_edges
from docsentry.intelligence.mapping.relationship_mapper import map_claims
from docsentry.intelligence.models.code import CodeEntity, CodeFact, ParsedSource
from docsentry.intelligence.models.common import AnalysisLimits, Side
from docsentry.intelligence.models.documentation import DocClaim, ParsedDocument
from docsentry.intelligence.models.relationships import Relationship


@dataclass
class BuiltSide:
    sources: tuple[ParsedSource, ...]
    docs: list[ParsedDocument]
    index: SymbolIndex
    graph: DependencyGraph
    claims: list[DocClaim]
    relationships: list[Relationship]
    entities: list[CodeEntity]
    facts: list[CodeFact]


def build_side(files: dict[str, str], sha: str, side: Side = Side.HEAD) -> BuiltSide:
    py = {p: t for p, t in files.items() if p.endswith(".py")}
    md = {p: t for p, t in files.items() if p.endswith(".md")}
    parsed = [parse_python(p, t, sha) for p, t in py.items()]
    index = SymbolIndex(parsed, list(files))
    resolved = resolve_value_references(parsed, index)
    index = SymbolIndex(resolved, list(files))
    graph = build_dependency_graph(resolved, index)
    docs = [parse_markdown(p, t, sha) for p, t in md.items()]
    claims = [c for d in docs for c in extract_claims(d)]
    entities = [e for s in resolved for e in s.entities]
    rels = map_claims(claims, entities, graph, docs, side, AnalysisLimits())
    add_documentation_edges(graph, rels, claims, docs, set(files))
    facts = [f for s in resolved for f in s.facts]
    return BuiltSide(resolved, docs, index, graph, claims, rels, entities, facts)
