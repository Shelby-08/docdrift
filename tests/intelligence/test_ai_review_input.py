from datetime import UTC, datetime

from docsentry.intelligence.models.analysis import UNTRUSTED_CONTENT_NOTICE, AnalysisContext
from docsentry.intelligence.models.common import AnalysisLimits
from docsentry.intelligence.pipeline import analyze_repositories
from docsentry.intelligence.reporting.json_exporter import to_json
from tests.intelligence.repos import make_repo

CTX = AnalysisContext(
    owner="o", repository="r", pull_number=1, base_sha="a" * 40, head_sha="b" * 40
)


def run(base: dict[str, str], head: dict[str, str], limits: AnalysisLimits | None = None):  # type: ignore[no-untyped-def]
    return analyze_repositories(
        make_repo(base, "a" * 40),
        make_repo(head, "b" * 40),
        CTX,
        limits or AnalysisLimits(),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_notice_and_finding_item() -> None:
    doc = "The default retries is 5.\n"
    res = run(
        {"src/c.py": "DEFAULT_RETRIES = 5\n", "docs/g.md": doc},
        {"src/c.py": "DEFAULT_RETRIES = 3\n", "docs/g.md": doc},
    )
    ai = res.ai_review_input
    assert ai.untrusted_content_notice == UNTRUSTED_CONTENT_NOTICE
    assert any(i.kind == "finding" and i.deterministic_finding_id for i in ai.items)


def test_ambiguous_relationship_item() -> None:
    code = {"src/a.py": "MAX_RETRIES = 3\n", "src/b.py": "MAX_RETRIES = 4\n"}
    res = run(code, {**code, "docs/g.md": "`MAX_RETRIES` defaults to 5.\n"})
    kinds = {i.kind for i in res.ai_review_input.items}
    assert "ambiguous_relationship" in kinds


def test_behavioral_candidate_item() -> None:
    res = run(
        {"src/a.py": "A = 1\n"},
        {"src/a.py": "A = 1\n", "docs/g.md": "The client intelligently retries failed requests.\n"},
    )
    assert [i.kind for i in res.ai_review_input.items] == ["behavioral_candidate"]


def test_indirect_dependency_item() -> None:
    code = "DEFAULT_TIMEOUT = {n}\n\ndef create_config(timeout=DEFAULT_TIMEOUT):\n    pass\n"
    doc = "Call `create_config` to build the object.\n"
    res = run(
        {"src/c.py": code.format(n=30), "docs/g.md": doc},
        {"src/c.py": code.format(n=60), "docs/g.md": doc},
    )
    assert "indirect_dependency" in {i.kind for i in res.ai_review_input.items}


def test_bounded_by_max_items_with_omitted_count() -> None:
    sentences = "\n\n".join(f"The service retries job {i} often." for i in range(6))
    res = run(
        {"src/a.py": "A = 1\n"},
        {"src/a.py": "A = 1\n", "docs/g.md": sentences + "\n"},
        AnalysisLimits(ai_review_max_items=2),
    )
    ai = res.ai_review_input
    assert len(ai.items) == 2 and ai.omitted_count == 4 and ai.complete is False


def test_json_redacts_non_finding_claim_text() -> None:
    res = run(
        {"src/a.py": "A = 1\n"},
        {"src/a.py": "A = 1\n", "docs/g.md": "The client intelligently retries failed requests.\n"},
    )
    assert "intelligently" not in to_json(res)
    assert "intelligently" in to_json(res, include_texts=True)
