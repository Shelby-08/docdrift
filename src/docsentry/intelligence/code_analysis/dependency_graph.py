from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple

from docsentry.intelligence.code_analysis.symbol_index import SymbolIndex, resolve_import
from docsentry.intelligence.models.code import ParsedSource
from docsentry.intelligence.models.common import Provenance

EdgeKind = Literal[
    "IMPORTS",
    "CALLS",
    "REFERENCES",
    "DEFINES",
    "CONFIGURES",
    "DOCUMENTS",
    "LINKS_TO",
]


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: EdgeKind
    resolved: bool
    evidence: Provenance
    dynamic: bool = False


class TraversalResult(NamedTuple):
    items: list[tuple[str, int, tuple[Edge, ...]]]
    truncated: bool


class DependencyGraph:
    def __init__(self) -> None:
        self._out_edges: dict[str, list[Edge]] = {}
        self._in_edges: dict[str, list[Edge]] = {}

    def add_edge(self, edge: Edge) -> None:
        self._out_edges.setdefault(edge.src, []).append(edge)
        self._in_edges.setdefault(edge.dst, []).append(edge)

    def out_edges(self, node_id: str) -> list[Edge]:
        return self._out_edges.get(node_id, [])

    def in_edges(self, node_id: str) -> list[Edge]:
        return self._in_edges.get(node_id, [])

    def reverse_reachable(
        self, node: str, max_depth: int = 10, max_nodes: int = 200
    ) -> TraversalResult:
        """Traverse incoming edges using explicit queue to find dependents/consumers."""
        results: list[tuple[str, int, tuple[Edge, ...]]] = []
        visited: set[str] = {node}
        queue: deque[tuple[str, int, tuple[Edge, ...]]] = deque([(node, 0, ())])
        truncated = False

        while queue:
            curr_node, curr_depth, curr_path = queue.popleft()

            if curr_depth >= max_depth:
                if self.in_edges(curr_node):
                    truncated = True
                continue

            for edge in self.in_edges(curr_node):
                neighbor = edge.src
                if neighbor in visited:
                    continue

                if len(visited) >= max_nodes:
                    truncated = True
                    break

                visited.add(neighbor)
                next_path = curr_path + (edge,)
                next_item = (neighbor, curr_depth + 1, next_path)
                results.append(next_item)
                queue.append((neighbor, curr_depth + 1, next_path))

            if truncated:
                break

        return TraversalResult(items=results, truncated=truncated)


def build_dependency_graph(
    parsed_sources: Sequence[ParsedSource], index: SymbolIndex
) -> DependencyGraph:
    graph = DependencyGraph()

    for src in parsed_sources:
        # 1. DEFINES: module -> top-level entities, class -> member methods/vars
        for ent in src.entities:
            if ent.container_id is None:
                graph.add_edge(
                    Edge(
                        src=src.path,
                        dst=ent.id,
                        kind="DEFINES",
                        resolved=True,
                        evidence=ent.provenance,
                    )
                )
            else:
                graph.add_edge(
                    Edge(
                        src=ent.container_id,
                        dst=ent.id,
                        kind="DEFINES",
                        resolved=True,
                        evidence=ent.provenance,
                    )
                )

            # 2. CONFIGURES: function/entity -> constant/config_key it references in defaults
            for param in ent.parameters:
                target_id = None
                if param.default:
                    if param.default.resolved_via:
                        target_id = param.default.resolved_via
                    elif param.default.source_expr:
                        target_id = index.resolve_name(src.path, param.default.source_expr)

                if target_id and target_id in index.by_id:
                    graph.add_edge(
                        Edge(
                            src=ent.id,
                            dst=target_id,
                            kind="CONFIGURES",
                            resolved=True,
                            evidence=ent.provenance,
                        )
                    )

        # 3. IMPORTS: module -> target module
        for imp in src.imports:
            target_path = resolve_import(src.path, imp, index.paths)
            if target_path:
                graph.add_edge(
                    Edge(
                        src=src.path,
                        dst=target_path,
                        kind="IMPORTS",
                        resolved=True,
                        evidence=imp.provenance,
                    )
                )

        # 4. CALLS: enclosing entity -> target
        for ref in src.references:
            # Find enclosing entity
            enclosing_id = src.path
            for ent in src.entities:
                if (
                    ent.provenance.line
                    <= ref.provenance.line
                    <= (ent.provenance.end_line or ent.provenance.line)
                ):
                    enclosing_id = ent.id
                    break

            resolved_id = index.resolve_name(src.path, ref.name)
            if resolved_id:
                graph.add_edge(
                    Edge(
                        src=enclosing_id,
                        dst=resolved_id,
                        kind="CALLS",
                        resolved=True,
                        evidence=ref.provenance,
                    )
                )
            else:
                graph.add_edge(
                    Edge(
                        src=enclosing_id,
                        dst=ref.name,
                        kind="CALLS",
                        resolved=False,
                        evidence=ref.provenance,
                    )
                )

    return graph
