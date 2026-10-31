from datetime import UTC, datetime

from docsentry.ai_review.models import (
    AIItemAssessment,
    AIReviewResult,
    AIReviewStatus,
    AIVerdict,
)
from docsentry.intelligence.models.findings import EvidenceStatus, TemporalStatus
from docsentry.reporting.check_run import build_report, esc, permalink
from tests.intelligence.test_pipeline import BASE, HEAD, run

SHA_H = "b" * 40


def drift():  # type: ignore[no-untyped-def]
    res = run(BASE, HEAD)
    assert len(res.findings) == 1
    return res


def test_new_drift_annotates_unchanged_doc_sentence_with_head_permalink() -> None:
    rep = build_report(drift())
    assert rep.conclusion == "neutral" and rep.new_findings == 1
    assert len(rep.annotations) == 1
    a = rep.annotations[0]
    assert (a.path, a.start_line) == ("docs/configuration.md", 3)
    assert a.annotation_level in ("warning", "notice")
    assert f"blob/{SHA_H}/src/config.py#L1" in rep.summary
    assert "failure" not in a.annotation_level


def test_clean_complete_result_is_success() -> None:
    rep = build_report(run(BASE, BASE))
    assert rep.conclusion == "success" and rep.annotations == ()


def test_incomplete_never_success() -> None:
    res = run(BASE, BASE).model_copy(update={"complete": False, "incomplete_reasons": ("x",)})
    rep = build_report(res)
    assert rep.conclusion == "neutral" and "PARTIAL" in rep.summary


def test_pre_existing_not_annotated_or_counted() -> None:
    res = drift()
    f = res.findings[0].model_copy(update={"temporal_status": TemporalStatus.PRE_EXISTING})
    rep = build_report(res.model_copy(update={"findings": (f,)}))
    assert rep.annotations == () and rep.new_findings == 0 and rep.conclusion == "success"
    assert "Other findings" in rep.summary


def test_ambiguous_new_finding_not_annotated() -> None:
    res = drift()
    f = res.findings[0].model_copy(
        update={"evidence_status": EvidenceStatus.AMBIGUOUS_RELATIONSHIP}
    )
    rep = build_report(res.model_copy(update={"findings": (f,)}))
    assert rep.annotations == () and rep.new_findings == 0


def test_hostile_text_is_escaped() -> None:
    res = drift()
    f = res.findings[0].model_copy(
        update={
            "affected_text": "<script>alert(1)</script> [x](http://evil.test) @bob",
            "description": "![i](http://e.test/a.png)",
        }
    )
    rep = build_report(res.model_copy(update={"findings": (f,)}))
    for bad in ("<script>", "http://evil", "http://e.test", "@bob"):
        assert bad not in rep.summary
    assert "http://evil" not in rep.annotations[0].message


def test_esc_bounds_and_flattens() -> None:
    out = esc("a\n\nb" + "x" * 1000, 50)
    assert "\n" not in out and len(out) <= 60


def test_permalink_validation_and_encoding() -> None:
    assert permalink("o", "r", SHA_H, "../etc/passwd", 1) is None
    assert permalink("o", "r", SHA_H, "/abs", 1) is None
    assert permalink("o", "r", "zz", "a.py", 1) is None
    assert (
        permalink("o", "r", SHA_H, "a b/c.py", 7)
        == f"https://github.com/o/r/blob/{SHA_H}/a%20b/c.py#L7"
    )


def test_grouping_cap_omitted_and_order() -> None:
    res = drift()
    base_f, base_c = res.findings[0], res.claims[0]
    findings, claims = [], []
    for i in range(1, 61):
        claims.append(base_c.model_copy(update={"claim_id": f"c{i}", "line": i, "end_line": i}))
        findings.append(base_f.model_copy(update={"finding_id": f"f{i}", "documentation_line": i}))
    dup = base_f.model_copy(update={"finding_id": "dup", "documentation_line": 1})
    big = res.model_copy(update={"claims": tuple(claims), "findings": (*findings, dup)})
    rep = build_report(big, max_annotations=25, max_summary_findings=5)
    assert len(rep.annotations) == 25 and rep.omitted_annotations == 35
    assert len({(a.path, a.start_line) for a in rep.annotations}) == 25
    assert "more not shown" in rep.summary
    assert build_report(big, max_annotations=25, max_summary_findings=5) == rep


def test_unverified_doc_line_gets_no_annotation() -> None:
    res = drift()
    f = res.findings[0].model_copy(update={"documentation_line": 999})
    rep = build_report(res.model_copy(update={"findings": (f,)}))
    assert rep.annotations == () and rep.new_findings == 1


def test_ai_section_is_advisory_and_status_shown() -> None:
    res = drift()
    ai = AIReviewResult(
        status=AIReviewStatus.COMPLETED,
        assessments=(
            AIItemAssessment(
                item_id="finding:x",
                verdict=AIVerdict.SUPPORTS_DRIFT,
                explanation="<b>ok</b>",
                evidence_ids=("E1",),
            ),
        ),
    )
    rep = build_report(res, ai)
    assert "advisory" in rep.summary and "supports_drift" in rep.summary
    assert "confirmed" not in rep.summary.split("AI-assisted")[1].lower()
    off = build_report(
        res, AIReviewResult(status=AIReviewStatus.UNAVAILABLE, error_code="ollama_unreachable")
    )
    assert "unavailable" in off.summary and off.conclusion == rep.conclusion


def test_generated_at_independent() -> None:
    assert datetime(2026, 1, 1, tzinfo=UTC) == drift().generated_at
