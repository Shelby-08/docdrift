from docsentry.intelligence.change_analysis.change_classifier import relevant_changes
from docsentry.intelligence.change_analysis.entity_matcher import match_entities
from docsentry.intelligence.change_analysis.semantic_diff import diff_entities
from docsentry.intelligence.code_analysis.python_parser import parse_python
from docsentry.intelligence.code_analysis.symbol_index import SymbolIndex, resolve_value_references
from docsentry.intelligence.models.changes import ChangedProperty, ChangeType, SemanticChange
from docsentry.intelligence.models.code import CodeEntity
from docsentry.intelligence.models.common import Exposure

SHA_A = "a" * 40
SHA_B = "b" * 40


def entities(files: dict[str, str], sha: str = SHA_A, resolve: bool = False) -> list[CodeEntity]:
    parsed = [parse_python(p, t, sha) for p, t in files.items()]
    if resolve:
        idx = SymbolIndex(parsed, list(files))
        parsed = list(resolve_value_references(parsed, idx))
    return [e for p in parsed for e in p.entities]


def diff(
    base: dict[str, str],
    head: dict[str, str],
    renames: dict[str, str] | None = None,
) -> tuple[list[SemanticChange], object]:
    m = match_entities(entities(base, SHA_A, True), entities(head, SHA_B, True), renames or {})
    return diff_entities(m), m


def props(changes: list[SemanticChange]) -> list[tuple[str, str, str | None]]:
    return [(c.change_type.value, c.property.value, c.detail) for c in changes]


def test_identity_match_and_no_change() -> None:
    src = "def f(a, b=1):\n    return a\n"
    changes, _ = diff({"m.py": src}, {"m.py": src})
    assert changes == []


def test_added_and_removed() -> None:
    changes, _ = diff({"m.py": "def old():\n    pass\n"}, {"m.py": "def new_thing(x):\n    pass\n"})
    assert sorted(c.change_type.value for c in changes) == ["added", "removed"]


def test_modified_default() -> None:
    changes, _ = diff({"m.py": "def f(a=1):\n    pass\n"}, {"m.py": "def f(a=2):\n    pass\n"})
    assert props(changes) == [("modified", "default_value", "a")]
    assert (changes[0].before, changes[0].after) == (1, 2)


def test_parameter_added_and_removed() -> None:
    changes, _ = diff({"m.py": "def f(a, b):\n    pass\n"}, {"m.py": "def f(a, c):\n    pass\n"})
    assert props(changes) == [
        ("modified", "parameter_added", "c"),
        ("modified", "parameter_removed", "b"),
    ]


def test_annotation_and_return_changes() -> None:
    changes, _ = diff(
        {"m.py": "def f(a: int) -> int:\n    pass\n"},
        {"m.py": "def f(a: str) -> str:\n    pass\n"},
    )
    assert {c.property for c in changes} == {
        ChangedProperty.PARAMETER_TYPE,
        ChangedProperty.RETURN_TYPE,
    }


def test_constant_value_and_exposure() -> None:
    changes, _ = diff({"m.py": "__all__ = ['X']\nX = 1\n"}, {"m.py": "__all__ = []\nX = 2\n"})
    assert {c.property for c in changes} == {
        ChangedProperty.CONSTANT_VALUE,
        ChangedProperty.EXPOSURE,
    }


def test_true_rename_function() -> None:
    changes, m = diff(
        {"m.py": "def fetch_user_data(user_id, timeout):\n    pass\n"},
        {"m.py": "def fetch_user_info(user_id, timeout):\n    pass\n"},
    )
    assert props(changes) == [("renamed", "entity", None)]
    assert changes[0].rename_confidence is not None


def test_constant_rename_enable_cache() -> None:
    changes, _ = diff({"m.py": "ENABLE_CACHE = True\n"}, {"m.py": "CACHE_ENABLED = True\n"})
    assert props(changes) == [("renamed", "entity", None)]


def test_not_rename_for_unrelated() -> None:
    changes, _ = diff(
        {"m.py": "def send_email(to):\n    pass\n"},
        {"m.py": "def compute_total(items, tax):\n    pass\n"},
    )
    assert sorted(c.change_type.value for c in changes) == ["added", "removed"]


def test_ambiguous_candidates_stay_removed_and_added() -> None:
    changes, m = diff(
        {"m.py": "def load_item(a):\n    pass\n"},
        {"m.py": "def load_items(a):\n    pass\n\ndef load_itemz(a):\n    pass\n"},
    )
    assert sorted(c.change_type.value for c in changes) == ["added", "added", "removed"]
    assert m.ambiguous  # type: ignore[attr-defined]


def test_file_rename_is_moved_not_removed_added() -> None:
    src = "def f(a):\n    pass\n"
    changes, _ = diff({"old.py": src}, {"new.py": src}, {"old.py": "new.py"})
    assert props(changes) == [("moved", "entity", None)]


def test_refactor_only_produces_no_changes() -> None:
    base = (
        '"""Mod."""\nX = 60 * 60\n\ndef a(p=1):\n    """Doc."""\n    t = 1\n    return t\n\n'
        "def b():\n    return 2\n"
    )
    head = (
        "X = 3600\n\n# new comment\ndef b():\n    return 2\n\n\n"
        'def a(p = 1):\n    """Different doc."""\n    local = 1\n    return local\n'
    )
    changes, _ = diff({"m.py": base}, {"m.py": head})
    assert changes == []


def test_unresolved_values_compared_by_source_expression() -> None:
    changes, _ = diff({"m.py": "X = foo(1)\n"}, {"m.py": "X = foo(2)\n"})
    assert len(changes) == 1 and "unresolved" in changes[0].evidence
    same, _ = diff({"m.py": "X = foo(1)\n"}, {"m.py": "X = foo( 1 )\n"})
    assert same == []


def test_indirect_constant_default_change() -> None:
    base = "DEFAULT_TIMEOUT = 30\ndef create_config(timeout=DEFAULT_TIMEOUT):\n    pass\n"
    head = base.replace("30", "60")
    changes, _ = diff({"m.py": base}, {"m.py": head})
    dv = [c for c in changes if c.property == ChangedProperty.DEFAULT_VALUE][0]
    assert (dv.before, dv.after) == (30, 60)
    assert any("DEFAULT_TIMEOUT" in e or "via" in e for e in dv.evidence)


def test_deterministic_and_private_flagged() -> None:
    b = {"m.py": "def _a(x=1):\n    pass\nB = 1\n"}
    h = {"m.py": "def _a(x=2):\n    pass\nB = 2\n"}
    c1, _ = diff(b, h)
    c2, _ = diff(b, h)
    assert c1 == c2
    rel = relevant_changes(c1)
    assert len(rel) == len(c1)
    flagged = {c.entity_name: c.low_relevance for c in rel}
    assert flagged["_a"] is True and flagged["B"] is False
    assert all(c.change_type == ChangeType.MODIFIED for c in rel)
    assert Exposure.PRIVATE in {c.exposure for c in rel}
