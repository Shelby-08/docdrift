import pytest
from pydantic import ValidationError

from docsentry.intelligence.models import (
    CodeDocMapping,
    DocBlock,
    DriftAnalysisReport,
    DriftFinding,
    ExtractedClaim,
    ParameterInfo,
    SymbolChange,
    SymbolSignature,
)


def test_intelligence_models_frozen_and_valid() -> None:
    p = ParameterInfo(name="x", type_annotation="int", default_value="0")
    with pytest.raises(ValidationError):
        p.name = "y"  # type: ignore[misc]

    sig = SymbolSignature(
        name="calc",
        qualified_name="calc",
        kind="function",
        parameters=[p],
        return_type="int",
        docstring="Calculate".strip(),
        line_start=1,
        line_end=5,
    )
    assert sig.parameters[0].name == "x"

    finding = DriftFinding(
        id="abc123456789",
        category="stale_reference",
        severity="critical",
        title="Stale ref",
        explanation="Expl",
        remediation="Rem",
        source_file="main.py",
        confidence=0.9,
    )
    assert finding.severity == "critical"
    assert finding.confidence == 0.9
