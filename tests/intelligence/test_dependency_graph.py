from docsentry.intelligence.code_analysis.dependency_graph import (
    DependencyGraph,
    Edge,
    build_dependency_graph,
)
from docsentry.intelligence.code_analysis.python_parser import parse_python
from docsentry.intelligence.code_analysis.symbol_index import (
    SymbolIndex,
    resolve_import,
    resolve_value_references,
)
from docsentry.intelligence.models.code import ImportRecord
from docsentry.intelligence.models.common import Provenance

SHA = "a" * 40


def test_import_resolution() -> None:
    paths = frozenset(
        {
            "src/pkg/a.py",
            "src/pkg/config.py",
            "src/pkg/sub/__init__.py",
            "src/pkg/sub/mod.py",
            "ambig.py",
            "src/ambig.py",
        }
    )
    prov = Provenance(path="src/pkg/a.py", commit_sha=SHA, line=1)

    # Relative import level 1: from .config import X
    rec_rel1 = ImportRecord(path="src/pkg/a.py", module="config", level=1, provenance=prov)
    assert resolve_import("src/pkg/a.py", rec_rel1, paths) == "src/pkg/config.py"

    # Relative import level 1 directory: from .sub import mod
    rec_sub = ImportRecord(path="src/pkg/a.py", module="sub", level=1, provenance=prov)
    assert resolve_import("src/pkg/a.py", rec_sub, paths) == "src/pkg/sub/__init__.py"

    # Relative import level 2: from ..config import X from src/pkg/sub/mod.py
    rec_rel2 = ImportRecord(path="src/pkg/sub/mod.py", module="config", level=2, provenance=prov)
    assert resolve_import("src/pkg/sub/mod.py", rec_rel2, paths) == "src/pkg/config.py"

    # Absolute import: from pkg.config import X
    rec_abs = ImportRecord(path="src/pkg/a.py", module="pkg.config", level=0, provenance=prov)
    assert resolve_import("src/pkg/a.py", rec_abs, paths) == "src/pkg/config.py"

    # Ambiguous candidate resolution returns None
    rec_ambig = ImportRecord(path="src/pkg/a.py", module="ambig", level=0, provenance=prov)
    assert resolve_import("src/pkg/a.py", rec_ambig, paths) is None


def test_symbol_resolution_and_alias_hop() -> None:
    src_const = """
BASE_TIMEOUT = 30
DEFAULT_TIMEOUT = BASE_TIMEOUT
SECOND_HOP = DEFAULT_TIMEOUT
"""
    src_app = """
from .const import DEFAULT_TIMEOUT

def run():
    pass
"""
    paths = ["pkg/const.py", "pkg/app.py"]
    p1 = parse_python("pkg/const.py", src_const, SHA)
    p2 = parse_python("pkg/app.py", src_app, SHA)
    index = SymbolIndex([p1, p2], paths)

    # Same file 1 alias hop: DEFAULT_TIMEOUT -> BASE_TIMEOUT
    resolved_id = index.resolve_name("pkg/const.py", "DEFAULT_TIMEOUT")
    base_ent = next(e for e in p1.entities if e.name == "BASE_TIMEOUT")
    assert resolved_id == base_ent.id

    # Imported name resolution through alias hop
    app_res_id = index.resolve_name("pkg/app.py", "DEFAULT_TIMEOUT")
    assert app_res_id == base_ent.id

    # Second hop is capped to 1 hop (so SECOND_HOP does not reach BASE_TIMEOUT)
    second_res = index.resolve_name("pkg/const.py", "SECOND_HOP")
    dt_ent = next(e for e in p1.entities if e.name == "DEFAULT_TIMEOUT")
    assert second_res == dt_ent.id


def test_parameter_default_reference_resolution() -> None:
    src_const = "DEFAULT_TIMEOUT = 45"
    src_cfg = """
from .const import DEFAULT_TIMEOUT

def create_config(timeout=DEFAULT_TIMEOUT):
    pass

def unknown_config(timeout=UNRESOLVED_NAME):
    pass
"""
    paths = ["pkg/const.py", "pkg/cfg.py"]
    p1 = parse_python("pkg/const.py", src_const, SHA)
    p2 = parse_python("pkg/cfg.py", src_cfg, SHA)
    index = SymbolIndex([p1, p2], paths)

    resolved_sources = resolve_value_references([p1, p2], index)
    cfg_src = next(s for s in resolved_sources if s.path == "pkg/cfg.py")
    create_fn = next(e for e in cfg_src.entities if e.name == "create_config")
    param = create_fn.parameters[0]
    assert param.default is not None
    assert param.default.resolved is True
    assert param.default.value == 45
    assert param.default.resolved_via is not None

    unk_fn = next(e for e in cfg_src.entities if e.name == "unknown_config")
    unk_param = unk_fn.parameters[0]
    assert unk_param.default is not None
    assert unk_param.default.resolved is False


def test_dependency_graph_traversal_and_reverse_reachability() -> None:
    src_const = "DEFAULT_TIMEOUT = 60"
    src_cfg = """
from .const import DEFAULT_TIMEOUT

def create_config(timeout=DEFAULT_TIMEOUT):
    return timeout
"""
    src_client = """
from .cfg import create_config

def initialize_client():
    cfg = create_config()
    return cfg
"""
    paths = ["pkg/const.py", "pkg/cfg.py", "pkg/client.py"]
    p1 = parse_python("pkg/const.py", src_const, SHA)
    p2 = parse_python("pkg/cfg.py", src_cfg, SHA)
    p3 = parse_python("pkg/client.py", src_client, SHA)
    index = SymbolIndex([p1, p2, p3], paths)
    resolved_sources = resolve_value_references([p1, p2, p3], index)
    new_index = SymbolIndex(resolved_sources, paths)
    graph = build_dependency_graph(resolved_sources, new_index)

    # Verify reverse reachability from DEFAULT_TIMEOUT reaches create_config and initialize_client
    const_ent = next(e for e in resolved_sources[0].entities if e.name == "DEFAULT_TIMEOUT")
    cfg_ent = next(e for e in resolved_sources[1].entities if e.name == "create_config")
    client_ent = next(e for e in resolved_sources[2].entities if e.name == "initialize_client")

    res, truncated = graph.reverse_reachable(const_ent.id, max_depth=5, max_nodes=50)
    assert truncated is False
    reached_nodes = [item[0] for item in res]
    assert cfg_ent.id in reached_nodes
    assert client_ent.id in reached_nodes

    # Test bounded traversal and truncation
    res_bound, truncated_bound = graph.reverse_reachable(const_ent.id, max_depth=1, max_nodes=50)
    assert cfg_ent.id in [item[0] for item in res_bound]
    assert client_ent.id not in [item[0] for item in res_bound]
    assert truncated_bound is True

    res_nodes, truncated_nodes = graph.reverse_reachable(const_ent.id, max_depth=5, max_nodes=1)
    assert truncated_nodes is True


def test_dependency_graph_cycle_safety() -> None:
    prov = Provenance(path="cycle.py", commit_sha=SHA, line=1)
    graph = DependencyGraph()
    # Create a cycle: A -> B -> C -> A
    graph.add_edge(Edge(src="B", dst="A", kind="CALLS", resolved=True, evidence=prov))
    graph.add_edge(Edge(src="C", dst="B", kind="CALLS", resolved=True, evidence=prov))
    graph.add_edge(Edge(src="A", dst="C", kind="CALLS", resolved=True, evidence=prov))

    res, truncated = graph.reverse_reachable("A", max_depth=10, max_nodes=10)
    assert truncated is False
    reached = {item[0] for item in res}
    assert reached == {"B", "C"}
