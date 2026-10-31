from docsentry.intelligence.models.common import ConsistencyState
from docsentry.intelligence.models.findings import EvidenceStatus
from tests.intelligence.drift_helpers import records

INC = ConsistencyState.INCONSISTENT


def one(files: dict[str, str], rule: str):  # type: ignore[no-untyped-def]
    recs = records(files, rule)
    assert len(recs) == 1, recs
    return recs[0]


def test_r1_confirmed_explicit_identifier() -> None:
    r = one({"src/c.py": "MAX_RETRIES = 3\n", "docs/g.md": "`MAX_RETRIES` defaults to 5.\n"}, "R1")
    assert r.state == INC and r.evidence_status == EvidenceStatus.CONFIRMED
    assert (r.doc_value, r.code_value) == (5, 3)


def test_r1_potential_token_match_only() -> None:
    r = one({"src/c.py": "DEFAULT_RETRIES = 3\n", "docs/g.md": "The default retries is 5.\n"}, "R1")
    assert r.state == INC and r.evidence_status == EvidenceStatus.POTENTIAL


def test_r1_unit_conversion() -> None:
    ok = one(
        {"src/c.py": "TIMEOUT_MS = 30000\n", "docs/g.md": "`TIMEOUT_MS` defaults to 30 seconds.\n"},
        "R1",
    )
    assert ok.state == ConsistencyState.CONSISTENT
    bad = one(
        {"src/c.py": "TIMEOUT_MS = 60000\n", "docs/g.md": "`TIMEOUT_MS` defaults to 30 seconds.\n"},
        "R1",
    )
    assert bad.state == INC and bad.evidence_status == EvidenceStatus.CONFIRMED


def test_r1_unit_unverified_caps_at_potential() -> None:
    r = one(
        {
            "src/c.py": "DEFAULT_TIMEOUT = 60\n",
            "docs/g.md": "`DEFAULT_TIMEOUT` defaults to 30 seconds.\n",
        },
        "R1",
    )
    assert r.state == INC and r.evidence_status == EvidenceStatus.POTENTIAL
    assert "unit_unverified" in r.reasons


def test_r1_ambiguous_target() -> None:
    r = one(
        {
            "src/a.py": "MAX_RETRIES = 3\n",
            "src/b.py": "MAX_RETRIES = 4\n",
            "docs/g.md": "`MAX_RETRIES` defaults to 5.\n",
        },
        "R1",
    )
    assert r.state == ConsistencyState.NOT_EVALUABLE
    assert r.evidence_status == EvidenceStatus.AMBIGUOUS_RELATIONSHIP


def test_r1_unresolved_value() -> None:
    r = one(
        {"src/c.py": "MAX_RETRIES = compute()\n", "docs/g.md": "`MAX_RETRIES` defaults to 5.\n"},
        "R1",
    )
    assert r.state == ConsistencyState.NOT_EVALUABLE
    assert r.evidence_status == EvidenceStatus.INSUFFICIENT_EVIDENCE


def test_r2_removed_parameter() -> None:
    recs = records(
        {
            "src/m.py": "def send(msg):\n    pass\n",
            "docs/g.md": "Use `send(msg, priority)` to send.\n",
        },
        "R2",
    )
    by_prop = {r.property: r for r in recs}
    assert by_prop["parameter:priority"].state == INC
    assert by_prop["parameter:priority"].evidence_status == EvidenceStatus.CONFIRMED
    assert by_prop["parameter:msg"].state == ConsistencyState.CONSISTENT


def test_r2_downgrades() -> None:
    doc = {"docs/g.md": "Use `send(msg, priority)` to send.\n"}
    for code in (
        "def send(msg, **kwargs):\n    pass\n",
        "from typing import overload\n@overload\ndef send(msg):\n    pass\n",
    ):
        recs = records({"src/m.py": code, **doc}, "R2")
        pr = [r for r in recs if r.property == "parameter:priority"][0]
        assert pr.state == INC and pr.evidence_status == EvidenceStatus.POTENTIAL, code


def test_r2_parameter_present_no_inconsistency() -> None:
    recs = records(
        {
            "src/m.py": "def send(msg, priority=1):\n    pass\n",
            "docs/g.md": "Use `send(msg, priority)` to send.\n",
        },
        "R2",
    )
    assert recs and all(r.state == ConsistencyState.CONSISTENT for r in recs)


def test_r2_parameter_mention_under_function_heading() -> None:
    recs = records(
        {
            "src/m.py": "def send(msg):\n    pass\n",
            "docs/g.md": "## send()\n\nThe `priority` parameter sets the priority.\n",
        },
        "R2",
    )
    assert [r.state for r in recs] == [INC]


def test_r2_redefined_function_is_never_confirmed() -> None:
    code = "def send(msg):\n    pass\ndef send(msg):\n    pass\n"
    recs = records(
        {"src/m.py": code, "docs/g.md": "Use `send(msg, priority)` to send.\n"},
        "R2",
    )
    assert recs and all(r.state == ConsistencyState.NOT_EVALUABLE for r in recs)
