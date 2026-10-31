from docsentry.intelligence.models.common import Strength
from docsentry.intelligence.models.documentation import ClaimType
from docsentry.intelligence.models.relationships import Relationship, SignalKind
from tests.intelligence.side import BuiltSide, build_side

SHA = "a" * 40


def rels_for(side: BuiltSide, ctype: ClaimType, subject: str | None = None) -> list[Relationship]:
    ids = {
        c.claim_id
        for c in side.claims
        if c.claim_type == ctype and (subject is None or c.subject == subject)
    }
    return [r for r in side.relationships if r.claim_id in ids]


def kinds(rel: Relationship) -> set[SignalKind]:
    return {s.kind for s in rel.signals}


def test_explicit_relative_link() -> None:
    side = build_side(
        {
            "src/config.py": "def helper_thing(x):\n    pass\n",
            "docs/guide.md": "# Guide\n\nSee [the config](../src/config.py) for `helper_thing()`.\n",
        },
        SHA,
    )
    rels = [r for r in side.relationships if SignalKind.EXPLICIT_REFERENCE in kinds(r)]
    assert rels and rels[0].strength == Strength.STRONG


def test_github_style_path_mention() -> None:
    side = build_side(
        {
            "src/config.py": "MAX_RETRIES = 3\n",
            "docs/guide.md": "Set MAX_RETRIES in src/config.py now.\n",
        },
        SHA,
    )
    rel = rels_for(side, ClaimType.CONFIGURATION_REFERENCE, "MAX_RETRIES")[0]
    assert {SignalKind.EXPLICIT_REFERENCE, SignalKind.EXACT_IDENTIFIER} <= kinds(rel)
    assert rel.strength == Strength.STRONG


def test_exact_symbol_max_retries() -> None:
    side = build_side(
        {"src/c.py": "MAX_RETRIES = 3\n", "docs/g.md": "Set MAX_RETRIES to control attempts.\n"},
        SHA,
    )
    rel = rels_for(side, ClaimType.CONFIGURATION_REFERENCE)[0]
    assert rel.strength == Strength.STRONG and not rel.ambiguous
    assert SignalKind.EXACT_IDENTIFIER in kinds(rel)


def test_heading_symbol_create_client() -> None:
    side = build_side(
        {
            "src/client.py": "def create_client(timeout=5):\n    pass\n",
            "docs/api.md": "## create_client()\n\nCreates it.\n",
        },
        SHA,
    )
    rel = rels_for(side, ClaimType.IDENTIFIER_REFERENCE, "create_client")[0]
    assert SignalKind.HEADING_SYMBOL in kinds(rel) and rel.strength == Strength.STRONG


def test_parameter_inside_function_heading_strong_vs_bare_medium() -> None:
    code = {"src/client.py": "def create_client(timeout=5):\n    pass\n"}
    strong = build_side(
        {**code, "docs/api.md": "## create_client()\n\nThe default timeout is 30 seconds.\n"}, SHA
    )
    rel = [r for r in rels_for(strong, ClaimType.CONFIGURATION_DEFAULT) if not r.ambiguous][0]
    assert rel.strength == Strength.STRONG
    assert SignalKind.CONFIG_OR_PARAMETER_NAME in kinds(rel)
    bare = build_side(
        {**code, "docs/api.md": "# Notes\n\nThe default timeout is 30 seconds.\n"}, SHA
    )
    rel2 = rels_for(bare, ClaimType.CONFIGURATION_DEFAULT)[0]
    assert rel2.strength == Strength.MEDIUM


def test_unchanged_doc_mapped_via_proximity_and_tokens() -> None:
    side = build_side(
        {
            "src/config.py": "DEFAULT_TIMEOUT = 30\n",
            "docs/configuration.md": "# Configuration\n\nThe default timeout is 30 seconds.\n",
        },
        SHA,
    )
    rel = rels_for(side, ClaimType.CONFIGURATION_DEFAULT)[0]
    assert rel.strength == Strength.MEDIUM
    assert {SignalKind.CONFIG_OR_PARAMETER_NAME, SignalKind.FILE_PROXIMITY} <= kinds(rel)


def test_duplicate_symbol_is_ambiguous() -> None:
    side = build_side(
        {
            "src/a.py": "MAX_RETRIES = 3\n",
            "src/b.py": "MAX_RETRIES = 5\n",
            "docs/g.md": "Set MAX_RETRIES to control attempts.\n",
        },
        SHA,
    )
    rel = rels_for(side, ClaimType.CONFIGURATION_REFERENCE)[0]
    assert rel.ambiguous and rel.target_entity_id is None and len(rel.alternatives) == 2
    assert list(rel.alternatives) == sorted(rel.alternatives)


def test_dependency_signal_only_is_medium() -> None:
    side = build_side(
        {
            "src/config.py": "DEFAULT_TIMEOUT = 30\ndef create_config(timeout=DEFAULT_TIMEOUT):\n    pass\n",
            "docs/x.md": "Call `create_config` to build the object.\n",
        },
        SHA,
    )
    by_name = {
        side.index.by_id[r.target_entity_id].name: r
        for r in side.relationships
        if r.target_entity_id
    }
    assert by_name["create_config"].strength == Strength.STRONG
    dep = by_name["DEFAULT_TIMEOUT"]
    assert kinds(dep) == {SignalKind.DEPENDENCY}
    assert dep.strength == Strength.MEDIUM


def test_weak_only_not_promoted() -> None:
    side = build_side(
        {
            "src/server.py": "def run_server(port):\n    pass\n",
            "docs/server.md": "# Notes\n\nThe default server banner is 3 lines.\n",
        },
        SHA,
    )
    for r in side.relationships:
        if kinds(r) <= {SignalKind.FILE_PROXIMITY, SignalKind.CONTEXTUAL}:
            assert r.strength != Strength.STRONG


def test_documents_and_links_edges_and_determinism() -> None:
    files = {
        "src/config.py": "MAX_RETRIES = 3\n",
        "docs/g.md": "Set MAX_RETRIES now. See [other](./other.md) and [gone](./gone.md).\n",
        "docs/other.md": "# Other\n",
    }
    a, b = build_side(files, SHA), build_side(files, SHA)
    assert a.relationships == b.relationships
    rel = a.relationships[0]
    docs_edges = a.graph.in_edges(rel.target_entity_id or "")
    assert any(e.kind == "DOCUMENTS" and e.evidence.path == "docs/g.md" for e in docs_edges)
    links = a.graph.out_edges("docs/g.md")
    resolved = {e.dst: e.resolved for e in links if e.kind == "LINKS_TO"}
    assert resolved == {"docs/other.md": True, "docs/gone.md": False}
