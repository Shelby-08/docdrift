"""Regression tests for defects found by running DocSentry on real projects and by review."""

from pathlib import Path
from typing import Any

import pytest

from docsentry.ai_review.models import AIReviewResult, AIReviewStatus
from docsentry.cli import main
from docsentry.intelligence.documentation.claim_extractor import is_history_doc
from docsentry.intelligence.models.common import AnalysisLimits
from docsentry.intelligence.models.findings import TemporalStatus
from tests.intelligence.test_pipeline import run
from tests.test_replay import default_history, repo  # noqa: F401


def new(res: Any) -> list[Any]:
    return [f for f in res.findings if f.temporal_status == TemporalStatus.NEWLY_INTRODUCED]


def one(doc: str, base_code: str, head_code: str, limits: AnalysisLimits | None = None) -> Any:
    return run(
        {"src/c.py": base_code, "docs/a.md": doc}, {"src/c.py": head_code, "docs/a.md": doc}, limits
    )


def test_removed_documented_function_with_signature_is_flagged() -> None:
    for doc in (
        "Call `legacy_connect(host, port)` to connect.\n",
        "Call legacy_connect(host, port).\n",
    ):
        res = run(
            {"src/c.py": "def legacy_connect(host, port=8080):\n    pass\n", "docs/a.md": doc},
            {"src/c.py": "def other():\n    pass\n", "docs/a.md": doc},
        )
        f = new(res)
        if "`" in doc:
            assert [x.rule_id for x in f] == ["R4"] and f[0].evidence_status.value == "confirmed"
        assert all(x.rule_id in ("R4", "R2") for x in f)


def test_still_defined_function_with_signature_has_no_finding() -> None:
    code = "def legacy_connect(host, port=8080):\n    pass\n"
    assert one("Call `legacy_connect(host, port)`.\n", code, code + "X = 1\n").findings == ()


BULLETS = (
    "# Options\n\n- `MAX_RETRIES`: Number of retry attempts. Defaults to 5.\n"
    "- `TIMEOUT`: Request timeout in seconds. Defaults to 30.\n"
)
PLAIN = (
    "Options\nMAX_RETRIES: Number of retry attempts. Defaults to 5.\n"
    "TIMEOUT: Request timeout in seconds. Defaults to 30.\n"
)


@pytest.mark.parametrize("doc", [BULLETS, PLAIN])
def test_default_on_next_sentence_inherits_subject(doc: str) -> None:
    res = one(doc, "MAX_RETRIES = 5\nTIMEOUT = 30\n", "MAX_RETRIES = 10\nTIMEOUT = 60\n")
    subjects = {
        c.subject: c.value for c in res.claims if c.claim_type.value == "configuration_default"
    }
    assert subjects == {"MAX_RETRIES": 5, "TIMEOUT": 30}
    assert sorted(f.documentation_line for f in new(res)) == sorted(
        {c.line for c in res.claims if c.claim_type.value == "configuration_default"}
    )
    assert len(new(res)) == 2


def test_inherited_default_does_not_cross_blocks() -> None:
    doc = "- `A_B`: first.\n\nDefaults to 5.\n"
    res = one(doc, "A_B = 5\n", "A_B = 6\n")
    assert [c for c in res.claims if c.claim_type.value == "configuration_default"] == []


def test_kind_word_between_name_and_defaults() -> None:
    doc = "The timeout parameter defaults to 30 seconds. The port option defaults to 8080.\n"
    res = one(doc, "TIMEOUT = 30\nPORT = 8080\n", "TIMEOUT = 60\nPORT = 9090\n")
    got = [
        (c.subject, c.value) for c in res.claims if c.claim_type.value == "configuration_default"
    ]
    assert got == [("timeout", 30), ("port", 8080)]
    assert len(new(res)) == 2
    ticked = one("The `port` option defaults to 8080.\n", "PORT = 8080\n", "PORT = 9090\n")
    assert [c.subject for c in ticked.claims if c.claim_type.value == "configuration_default"] == [
        "port"
    ]


def test_scientific_notation_is_parsed_not_truncated() -> None:
    doc = "`LEARNING_RATE` defaults to 1e-3.\n"
    same = one(doc, "LEARNING_RATE = 1e-3\n", "LEARNING_RATE = 1e-3\nX = 1\n")
    assert [c.value for c in same.claims if c.claim_type.value == "configuration_default"] == [
        0.001
    ]
    assert same.findings == ()
    drift = new(one(doc, "LEARNING_RATE = 1e-3\n", "LEARNING_RATE = 1e-4\n"))
    assert (
        len(drift) == 1
        and drift[0].old_value in (0.001, None)
        and "is 0.001" in drift[0].description
    )


def test_suggested_correction_uses_the_documented_unit() -> None:
    res = one(
        "`TIMEOUT_MS` defaults to 30 seconds.\n", "TIMEOUT_MS = 30000\n", "TIMEOUT_MS = 60000\n"
    )
    f = new(res)
    assert len(f) == 1
    assert f[0].suggested_correction == "Update the documented value 30 seconds to 60 seconds"


def test_negative_default_is_extracted_and_compared() -> None:
    for doc in ("`TIMEOUT` defaults to -1.\n", "timeout defaults to -1.\n"):
        res = one(doc, "TIMEOUT = -1\n", "TIMEOUT = 5\n")
        vals = [c.value for c in res.claims if c.claim_type.value == "configuration_default"]
        assert vals == [-1], doc
        assert len(new(res)) == 1, doc
    assert (
        one("`TIMEOUT` defaults to -1.\n", "TIMEOUT = -1\n", "TIMEOUT = -1\nX = 1\n").findings == ()
    )


def test_multiword_table_headers_and_cli_flags() -> None:
    t1 = "| Parameter Name | Default Value |\n|---|---|\n| `TIMEOUT` | 30 |\n"
    assert len(new(one(t1, "TIMEOUT = 30\n", "TIMEOUT = 60\n"))) == 1
    t2 = "| Option | Default |\n|---|---|\n| `--port` | 8080 |\n"
    res = one(t2, "PORT = 8080\n", "PORT = 9090\n")
    assert [c.subject for c in res.claims if c.claim_type.value == "configuration_default"] == [
        "port"
    ]
    assert len(new(res)) == 1


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("CHANGELOG.md", True),
        ("docs/release-notes.md", True),
        ("docs/changelog/0.28.md", True),
        ("HISTORY.markdown", True),
        ("docs/configuration.md", False),
        ("docs/changes-to-config-guide.md", False),
        ("README.md", False),
    ],
)
def test_history_docs_detection(path: str, expected: bool) -> None:
    assert is_history_doc(path) is expected


def test_changelog_describing_removed_params_is_not_drift() -> None:
    log = "## 0.28\n\n* The `URL.join(relative_url=...)` method is now `URL.join(url=...)`.\n* Removed `legacy_sync` helper.\n"
    code_b = "class URL:\n    def join(self, url):\n        pass\n\ndef legacy_sync():\n    pass\n"
    base = {"src/c.py": code_b, "CHANGELOG.md": log}
    head = {
        "src/c.py": code_b.replace("def legacy_sync():\n    pass\n", "def other():\n    pass\n"),
        "CHANGELOG.md": log + "* More.\n",
    }
    res = run(base, head)
    assert res.findings == () and res.claims == ()


def test_depth_limit_is_not_reported_as_incomplete() -> None:
    code = "BASE = 10\nDEFAULT_TIMEOUT = BASE\n\ndef create_config(timeout=DEFAULT_TIMEOUT):\n    pass\n"
    res = one(
        "Call `create_config` to build it.\n",
        code,
        code + "Z = 1\n",
        AnalysisLimits(max_graph_depth=1),
    )
    assert res.complete is True and "graph_traversal_truncated" not in res.incomplete_reasons


# ---- replay --ai ----
class FakeReviewer:
    calls = 0

    def __init__(self, settings: Any, client: Any = None) -> None:
        FakeReviewer.settings = settings  # type: ignore[attr-defined]

    async def review(self, result: Any) -> AIReviewResult:
        FakeReviewer.calls += 1
        return AIReviewResult(status=AIReviewStatus.UNAVAILABLE, error_code="ollama_unreachable")


def test_replay_ai_flag_runs_advisory_review(
    repo: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import docsentry.cli as cli

    c0, c1, _ = default_history(repo)
    monkeypatch.setattr(cli, "OllamaAIReviewer", FakeReviewer)
    FakeReviewer.calls = 0
    assert main(["replay", "--repo", str(repo), "--base", c0, "--head", c1]) == 0
    assert FakeReviewer.calls == 0 and "AI-assisted" not in capsys.readouterr().out
    args = ["replay", "--repo", str(repo), "--base", c0, "--head", c1, "--ai"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert FakeReviewer.calls == 1 and "AI-assisted" in out and "unavailable" in out
    assert "docs/configuration.md" in out  # deterministic finding still shown
    s = FakeReviewer.settings  # type: ignore[attr-defined]
    assert s.ai_backend == "llama_cpp" and s.ollama_base_url == "http://127.0.0.1:8080"
    assert main([*args, "--ai-url", "http://example.com:8080"]) == 2


def test_unconvertible_time_units_do_not_leave_a_bare_number() -> None:
    for doc in (
        "`max_age` defaults to 2 weeks.\n",
        "- `max_age`: Session lifetime. Defaults to 2 weeks.\n",
    ):
        res = one(doc, "MAX_AGE = 600\n", "MAX_AGE = 700\n")
        assert [c for c in res.claims if c.claim_type.value == "configuration_default"] == [], doc
        assert res.findings == ()
    ok = one("`max_age` defaults to 14 days.\n", "MAX_AGE = 14\n", "MAX_AGE = 15\n")
    assert [c.value for c in ok.claims if c.claim_type.value == "configuration_default"] == [14]


def test_direct_bullet_defaults_without_middle_sentence() -> None:
    doc = "# Options\n\n- `MAX_RETRIES`: Defaults to 5.\n- `TIMEOUT`: Defaults to 30.\n"
    res = one(doc, "MAX_RETRIES = 5\nTIMEOUT = 30\n", "MAX_RETRIES = 10\nTIMEOUT = 60\n")
    f = new(res)
    assert len(f) == 2
    assert {x.rule_id for x in f} == {"R1"}
    ctrl = one(doc, "MAX_RETRIES = 5\nTIMEOUT = 30\n", "MAX_RETRIES = 5\nTIMEOUT = 30\n")
    assert ctrl.findings == ()


def test_plural_table_headers() -> None:
    doc = "| Parameters | Default |\n|---|---|\n| `port` | 8080 |\n| `timeout` | 30 |\n"
    res = one(doc, "PORT = 8080\nTIMEOUT = 30\n", "PORT = 9090\nTIMEOUT = 60\n")
    assert len(new(res)) == 2
    ctrl = one(doc, "PORT = 8080\nTIMEOUT = 30\n", "PORT = 8080\nTIMEOUT = 30\n")
    assert ctrl.findings == ()


def test_heading_signature_parameter_removal() -> None:
    doc = "## `connect(host, port, timeout)`\nConnect to server.\n"
    res = one(
        doc,
        "def connect(host, port, timeout=30):\n    pass\n",
        "def connect(host, port):\n    pass\n",
    )
    f = new(res)
    assert len(f) == 1
    assert f[0].rule_id == "R2"
    assert "timeout" in f[0].description
    ctrl = one(
        doc,
        "def connect(host, port, timeout=30):\n    pass\n",
        "def connect(host, port, timeout=30):\n    pass\n",
    )
    assert ctrl.findings == ()


def test_typed_parameters_and_parenthetical_defaults() -> None:
    doc = (
        "- `timeout` (int): Defaults to 30.\n"
        "- `retries` (default: 3): Number of attempts.\n"
        "- `cache_size` (int, default: 100): Size.\n"
    )
    base = "TIMEOUT = 30\nRETRIES = 3\nCACHE_SIZE = 100\n"
    head = "TIMEOUT = 60\nRETRIES = 5\nCACHE_SIZE = 200\n"
    res = one(doc, base, head)
    assert len(new(res)) == 3
    ctrl = one(doc, base, base)
    assert ctrl.findings == ()


def test_heading_function_with_parameter_default_mapping() -> None:
    doc = "# Client\n\n## `connect(host, port, timeout=30)`\n\n- `timeout`: Defaults to 30.\n"
    base = "def connect(host, port, timeout=30):\n    pass\n"
    head = "def connect(host, port, timeout=60):\n    pass\n"
    res = one(doc, base, head)
    f = new(res)
    assert len(f) == 1
    assert f[0].rule_id == "R1"
    assert f[0].evidence_status.value == "confirmed"

