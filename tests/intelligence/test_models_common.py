import pytest
from pydantic import ValidationError

from docsentry.config import Settings
from docsentry.intelligence.models.common import (
    AnalysisLimits,
    Certainty,
    ConsistencyState,
    Exposure,
    FileClass,
    Provenance,
    Side,
    SkippedAnalysisFile,
    Strength,
    ValueRepr,
)


def test_models_common_enums_and_dataclasses() -> None:
    assert Side.BASE == "base"
    assert Side.HEAD == "head"
    assert FileClass.SOURCE == "source"
    assert Exposure.PUBLIC == "public"
    assert Certainty.HIGH == "high"
    assert Strength.STRONG == "strong"
    assert ConsistencyState.CONSISTENT == "consistent"

    prov = Provenance(
        path="src/main.py",
        commit_sha="a" * 40,
        line=10,
        snippet="def foo(): pass",
    )
    assert prov.line == 10
    with pytest.raises(ValidationError):
        prov.line = 20  # type: ignore[misc]

    val = ValueRepr(resolved=True, value=42, source_expr="42")
    assert val.resolved is True
    assert val.value == 42

    skipped = SkippedAnalysisFile(path="big.py", side=Side.BASE, reason="oversized")
    assert skipped.reason == "oversized"

    settings = Settings(
        github_app_id="123",
        github_private_key="key",
        github_webhook_secret="sec",
        analysis_max_source_files=300,
    )
    limits = AnalysisLimits.from_settings(settings)
    assert limits.max_source_files == 300
    assert limits.time_budget_seconds == 60
