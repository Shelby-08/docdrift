from docsentry.intelligence.detector import detect_drift
from docsentry.intelligence.models import (
    CodeDocMapping,
    DocBlock,
    ExtractedClaim,
    ParameterInfo,
    SymbolChange,
    SymbolSignature,
)


def test_detect_drift_scenarios() -> None:
    sig_old = SymbolSignature(
        name="old_func",
        qualified_name="old_func",
        kind="function",
        parameters=[],
        line_start=1,
        line_end=3,
    )

    changes = [
        SymbolChange(
            file_path="src/core.py",
            symbol_name="old_func",
            qualified_name="old_func",
            change_kind="removed",
            before=sig_old,
            breaking=True,
        ),
        SymbolChange(
            file_path="src/core.py",
            symbol_name="new_func",
            qualified_name="new_func",
            change_kind="added",
            after=sig_old,
            breaking=False,
        ),
    ]

    claims = [
        ExtractedClaim(
            file_path="docs/arch.md",
            line_number=10,
            claim_kind="symbol_mention",
            target_symbol="old_func",
            extracted_text="`old_func`",
        )
    ]

    report = detect_drift(changes, claims, [], [])
    assert report.critical_count == 1  # stale reference to removed symbol
    assert report.info_count == 1  # undocumented added symbol
    assert any(f.category == "stale_reference" for f in report.findings)
    assert any(f.category == "undocumented_change" for f in report.findings)
