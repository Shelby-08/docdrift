import socket
from datetime import UTC, datetime

import pytest

from docsentry.config import Settings
from docsentry.intelligence.models.analysis import AnalysisContext
from docsentry.intelligence.models.common import AnalysisLimits
from docsentry.intelligence.models.findings import TemporalStatus
from docsentry.intelligence.pipeline import analyze_bundle, analyze_repositories
from docsentry.intelligence.reporting.json_exporter import to_json
from tests.intelligence.bundles import make_bundle
from tests.intelligence.repos import make_repo

FIXED = datetime(2026, 1, 1, tzinfo=UTC)
CTX = AnalysisContext(
    owner="o", repository="r", pull_number=1, base_sha="a" * 40, head_sha="b" * 40
)
DOC = "# Configuration\n\nThe default timeout is 30 seconds.\n"
BASE = {"src/config.py": "DEFAULT_TIMEOUT = 30\n", "docs/configuration.md": DOC}
HEAD = {"src/config.py": "DEFAULT_TIMEOUT = 60\n", "docs/configuration.md": DOC}


def run(base: dict[str, str], head: dict[str, str], limits: AnalysisLimits | None = None, **kw):  # type: ignore[no-untyped-def]
    return analyze_repositories(
        make_repo(base, "a" * 40),
        make_repo(head, "b" * 40),
        CTX,
        limits or AnalysisLimits(),
        clock=lambda: FIXED,
        **kw,
    )


def settings(**kw: object) -> Settings:
    return Settings(
        github_app_id="1",
        github_private_key="k",
        github_webhook_secret="s",
        **kw,  # type: ignore[arg-type]
    )


def test_required_end_to_end_newly_introduced() -> None:
    res = run(BASE, HEAD)
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.temporal_status == TemporalStatus.NEWLY_INTRODUCED
    assert (f.code_file, f.code_line) == ("src/config.py", 1)
    assert (f.documentation_file, f.documentation_line) == ("docs/configuration.md", 3)
    assert res.complete is True
    assert res.stats["changed_doc_files"] == 0  # docs unchanged in the PR, finding still produced
    assert res.entities_count == {"base": 1, "head": 1}


def test_pure_refactor_zero_findings() -> None:
    base = {
        "src/config.py": "DEFAULT_TIMEOUT = 30\n\ndef run(retries=3):\n    '''Doc.'''\n    return retries\n",
        "docs/configuration.md": DOC,
    }
    head = {
        "src/config.py": "def run(retries=3):\n    # comment\n    return retries\n\n\nDEFAULT_TIMEOUT = 30\n",
        "docs/configuration.md": DOC,
    }
    res = run(base, head)
    assert res.findings == () and res.semantic_changes == ()


def test_unsupported_language_listed_and_incomplete() -> None:
    res = run(
        {**BASE, "web/app.ts": "export const a = 1;\n"},
        {**HEAD, "web/app.ts": "export const a = 2;\n"},
    )
    assert any(
        s.path == "web/app.ts" and s.reason == "unsupported_language" for s in res.skipped_files
    )
    assert res.complete is False


def test_invalid_syntax_recorded_and_rest_analyzed() -> None:
    res = run(BASE, {**HEAD, "src/broken.py": "def (:\n"})
    assert any(s.path == "src/broken.py" and s.reason == "syntax_error" for s in res.skipped_files)
    assert res.parse_errors and res.complete is False
    assert len(res.findings) == 1


def test_malformed_markdown_handled() -> None:
    docs = {"docs/bad.md": "```python\nunclosed\n\n| a | b\n|--\n[x]: \n"}
    res = run({**BASE, **docs}, {**HEAD, **docs})
    assert len(res.findings) == 1


def test_time_budget_partial_with_warning() -> None:
    ticks = iter(range(0, 100000, 100))
    res = run(
        BASE, HEAD, AnalysisLimits(time_budget_seconds=1), monotonic=lambda: float(next(ticks))
    )
    assert res.complete is False
    assert "time_budget" in res.incomplete_reasons and res.warnings
    assert any(s.reason == "time_budget" for s in res.skipped_files)


def test_analyze_bundle_with_fake_source_and_renames() -> None:
    base = {"src/config.py": "DEFAULT_TIMEOUT = 30\n", "docs/old.md": DOC}
    head = {"src/config.py": "DEFAULT_TIMEOUT = 60\n", "docs/new.md": DOC}
    bundle, source = make_bundle(base, head, renames={"docs/old.md": "docs/new.md"})
    res = analyze_bundle(bundle, source, settings(), clock=lambda: FIXED)
    assert res.context.base_sha == bundle.context.merge_base_sha
    assert res.context.original_base_sha == bundle.context.base_sha
    assert [f.temporal_status for f in res.findings] == [TemporalStatus.NEWLY_INTRODUCED]
    assert res.findings[0].documentation_file == "docs/new.md"


def test_oversized_file_skipped_via_bundle() -> None:
    base = {"src/config.py": "DEFAULT_TIMEOUT = 30\n", "src/big.py": "B = 1\n"}
    head = {"src/config.py": "DEFAULT_TIMEOUT = 60\n", "src/big.py": "B = 2\n"}
    bundle, source = make_bundle(base, head, seed_snapshots=False)
    source.oversized.add("src/big.py")
    res = analyze_bundle(bundle, source, settings(), clock=lambda: FIXED)
    assert any(s.path == "src/big.py" and s.reason == "oversized" for s in res.skipped_files)
    assert res.complete is False


def test_json_export_deterministic_and_redacts_texts() -> None:
    a, b = run(BASE, HEAD), run(BASE, HEAD)
    assert to_json(a) == to_json(b)
    assert to_json(a, include_texts=True) == to_json(b, include_texts=True)
    redacted = to_json(a)
    assert "The default timeout is 30 seconds." not in redacted.replace(
        a.findings[0].affected_text, ""
    )
    full = to_json(a, include_texts=True)
    assert '"original_text": "The default timeout is 30 seconds."' in full


def test_include_full_entities_flag() -> None:
    assert run(BASE, HEAD).entities == ()
    full = run(BASE, HEAD, AnalysisLimits(include_full_entities=True))
    assert len(full.entities) == 1


def test_no_network_access_during_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: object, **k: object) -> None:
        raise AssertionError("network used")

    bundle, source = make_bundle(BASE, HEAD)
    monkeypatch.setattr(socket, "socket", boom)
    res = analyze_bundle(bundle, source, settings(), clock=lambda: FIXED)
    assert len(res.findings) == 1
