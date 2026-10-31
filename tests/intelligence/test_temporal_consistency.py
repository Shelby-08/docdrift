from docsentry.intelligence.drift.consistency_checker import classify_temporal
from docsentry.intelligence.models.common import ConsistencyState
from docsentry.intelligence.models.findings import EvidenceStatus, TemporalStatus
from tests.intelligence.drift_helpers import analyze, records

CODE30 = "DEFAULT_TIMEOUT = 30\n"
DOC = "# Config\n\nThe default timeout is {n} seconds.\n"


def files(code: str, doc_n: int) -> dict[str, str]:
    return {"src/config.py": code, "docs/configuration.md": DOC.format(n=doc_n)}


def statuses(res) -> list[str]:  # type: ignore[no-untyped-def]
    return [f.temporal_status.value for f in res.findings]


def test_required_newly_introduced_with_locations() -> None:
    res = analyze(files(CODE30, 30), files("DEFAULT_TIMEOUT = 60\n", 30))
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.temporal_status == TemporalStatus.NEWLY_INTRODUCED
    assert f.introduced_by_current_pr is True
    assert (f.code_file, f.code_line) == ("src/config.py", 1)
    assert (f.documentation_file, f.documentation_line) == ("docs/configuration.md", 3)
    assert (f.old_value, f.new_value) == (30, 60)
    assert f.rule_id == "R1"


def test_resolved_when_doc_updated_to_match() -> None:
    res = analyze(files(CODE30, 20), files("DEFAULT_TIMEOUT = 60\n", 60))
    assert statuses(res) == ["resolved"]
    assert res.findings[0].introduced_by_current_pr is False


def test_pre_existing_when_still_wrong() -> None:
    res = analyze(files(CODE30, 20), files("DEFAULT_TIMEOUT = 60\n", 20))
    assert statuses(res) == ["pre_existing"]


def test_doc_corrected_in_same_pr_keeps_identity() -> None:
    res = analyze(files(CODE30, 20), files(CODE30, 30), changed_docs={"docs/configuration.md"})
    assert statuses(res) == ["resolved"]


def test_untouched_inconsistent_pair_not_emitted() -> None:
    res = analyze(files(CODE30, 20), files(CODE30, 20))
    assert res.findings == []
    assert res.stats["untouched_pairs"] == 1


def test_doc_added_in_pr_with_wrong_value_is_new() -> None:
    res = analyze(
        {"src/config.py": CODE30}, files(CODE30, 20), changed_docs={"docs/configuration.md"}
    )
    assert statuses(res) == ["newly_introduced"]


def test_indeterminate_when_base_not_evaluable_and_untouched() -> None:
    recs = records(files(CODE30, 20))
    (rec,) = [r for r in recs.__iter__()]
    base = {rec.key: rec.model_copy(update={"state": ConsistencyState.NOT_EVALUABLE})}
    head = {rec.key: rec}
    found = classify_temporal(base, head, lambda _k: False)
    assert [f.temporal_status for f in found] == [TemporalStatus.INDETERMINATE]
    assert found[0].introduced_by_current_pr is None


def test_head_not_evaluable_only_if_touched() -> None:
    recs = records(files(CODE30, 20))
    rec = recs[0]
    head = {
        rec.key: rec.model_copy(
            update={
                "state": ConsistencyState.NOT_EVALUABLE,
                "evidence_status": EvidenceStatus.INSUFFICIENT_EVIDENCE,
            }
        )
    }
    assert classify_temporal({rec.key: rec}, head, lambda _k: False) == []
    out = classify_temporal({rec.key: rec}, head, lambda _k: True)
    assert [f.temporal_status for f in out] == [TemporalStatus.INSUFFICIENT_EVIDENCE]


def test_pure_refactor_has_zero_findings() -> None:
    base = {
        "src/config.py": "DEFAULT_TIMEOUT = 30\ndef connect(retries=3):\n    '''Doc.'''\n    x = 1\n    return x\n",
        "docs/configuration.md": "# Config\n\nThe default timeout is 30 seconds. Use `connect(retries)`.\n",
    }
    head = {
        "src/config.py": "def connect(retries=3):\n    # moved docstring\n    y = 1\n    return y\n\n# note\nDEFAULT_TIMEOUT = 30\n",
        "docs/configuration.md": base["docs/configuration.md"],
    }
    res = analyze(base, head)
    assert res.findings == []


def test_indirect_constant_default_change() -> None:
    code = "DEFAULT_TIMEOUT = {n}\n\ndef create_config(timeout=DEFAULT_TIMEOUT):\n    pass\n"
    doc = "## create_config()\n\nThe default timeout is 30 seconds.\n"
    res = analyze(
        {"src/config.py": code.format(n=30), "docs/api.md": doc},
        {"src/config.py": code.format(n=60), "docs/api.md": doc},
    )
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.temporal_status == TemporalStatus.NEWLY_INTRODUCED
    assert any("DEFAULT_TIMEOUT" in e.description for e in f.evidence)


def test_finding_ids_stable() -> None:
    a = analyze(files(CODE30, 30), files("DEFAULT_TIMEOUT = 60\n", 30))
    b = analyze(files(CODE30, 30), files("DEFAULT_TIMEOUT = 60\n", 30))
    assert [f.finding_id for f in a.findings] == [f.finding_id for f in b.findings]
    assert a.findings == b.findings


# --- R3 / R4 -------------------------------------------------------------------


def test_r3_renamed_config_key_with_suggestion() -> None:
    doc = {"docs/g.md": "Set ENABLE_CACHE to toggle caching.\n"}
    res = analyze(
        {"src/c.py": "ENABLE_CACHE = True\n", **doc}, {"src/c.py": "CACHE_ENABLED = True\n", **doc}
    )
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.rule_id == "R3" and f.temporal_status == TemporalStatus.NEWLY_INTRODUCED
    assert f.evidence_status == EvidenceStatus.CONFIRMED
    assert f.suggested_correction and "CACHE_ENABLED" in f.suggested_correction


def test_r3_alias_at_head_no_finding() -> None:
    doc = {"docs/g.md": "Set ENABLE_CACHE to toggle caching.\n"}
    res = analyze(
        {"src/c.py": "ENABLE_CACHE = True\n", **doc},
        {"src/c.py": "CACHE_ENABLED = True\nENABLE_CACHE = CACHE_ENABLED\n", **doc},
    )
    assert res.findings == []


def test_r3_incomplete_head_snapshot_is_insufficient() -> None:
    doc = {"docs/g.md": "Set ENABLE_CACHE to toggle caching.\n"}
    res = analyze(
        {"src/c.py": "ENABLE_CACHE = True\n", **doc},
        {"src/c.py": "CACHE_ENABLED = True\n", **doc},
        head_complete=False,
    )
    assert [f.evidence_status for f in res.findings] == [EvidenceStatus.INSUFFICIENT_EVIDENCE]


def test_r4_removed_function_and_ignored_unknown() -> None:
    doc = {"docs/g.md": "Call `create_client()` to start. Also `ghost_func()` exists.\n"}
    res = analyze(
        {"src/c.py": "def create_client():\n    pass\n", **doc},
        {"src/c.py": "def other_thing(x):\n    pass\n", **doc},
    )
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.rule_id == "R4" and "create_client" in f.description


def test_r4_module_getattr_downgrades() -> None:
    doc = {"docs/g.md": "Call `create_client()` to start.\n"}
    res = analyze(
        {"src/c.py": "def create_client():\n    pass\n", **doc},
        {"src/c.py": "def __getattr__(name):\n    raise AttributeError(name)\n", **doc},
    )
    assert [f.evidence_status for f in res.findings] == [EvidenceStatus.POTENTIAL]
