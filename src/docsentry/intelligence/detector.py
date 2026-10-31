import hashlib
from docsentry.intelligence.models import (
    CodeDocMapping,
    DocBlock,
    DriftAnalysisReport,
    DriftFinding,
    ExtractedClaim,
    SymbolChange,
)


def _generate_id(category: str, source: str, doc: str | None, symbol: str | None) -> str:
    content = f"{category}:{source}:{doc or ''}:{symbol or ''}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def detect_drift(
    symbol_changes: list[SymbolChange],
    claims: list[ExtractedClaim],
    mappings: list[CodeDocMapping],
    doc_blocks: list[DocBlock],
) -> DriftAnalysisReport:
    """Detect documentation drift deterministically by cross-referencing symbol changes with docs."""
    findings: list[DriftFinding] = []
    doc_claims_by_target: dict[str, list[ExtractedClaim]] = {}
    for c in claims:
        doc_claims_by_target.setdefault(c.target_symbol, []).append(c)

    # Track documented symbols
    documented_symbols = set(doc_claims_by_target.keys())

    # 1. Stale References: Symbol was removed or renamed in code but still referenced in docs
    for change in symbol_changes:
        if change.change_kind == "removed":
            target_claims = doc_claims_by_target.get(change.symbol_name, []) + doc_claims_by_target.get(
                change.qualified_name, []
            )
            for cl in target_claims:
                finding_id = _generate_id(
                    "stale_reference", change.file_path, cl.file_path, change.qualified_name
                )
                findings.append(
                    DriftFinding(
                        id=finding_id,
                        category="stale_reference",
                        severity="critical",
                        title=f"Stale reference to removed symbol '{change.qualified_name}'",
                        explanation=(
                            f"The symbol '{change.qualified_name}' was removed from {change.file_path}, "
                            f"but documentation file {cl.file_path} still references it at line {cl.line_number}."
                        ),
                        remediation=f"Update {cl.file_path} to remove or replace reference to '{change.qualified_name}'.",
                        source_file=change.file_path,
                        doc_file=cl.file_path,
                        symbol_name=change.qualified_name,
                        line_number=cl.line_number,
                        confidence=0.95,
                    )
                )

    # 2. Broken Contracts: Signature changed (params removed or required added), but doc quotes old signature
    for change in symbol_changes:
        if change.change_kind == "signature_changed":
            target_claims = doc_claims_by_target.get(change.symbol_name, []) + doc_claims_by_target.get(
                change.qualified_name, []
            )
            for cl in target_claims:
                severity = "critical" if change.breaking else "warning"
                finding_id = _generate_id(
                    "broken_contract", change.file_path, cl.file_path, change.qualified_name
                )
                findings.append(
                    DriftFinding(
                        id=finding_id,
                        category="broken_contract",
                        severity=severity,
                        title=f"Signature contract drift for '{change.qualified_name}'",
                        explanation=(
                            f"Symbol '{change.qualified_name}' signature changed ({change.details}) in {change.file_path}, "
                            f"which affects documentation claim in {cl.file_path} at line {cl.line_number}."
                        ),
                        remediation=f"Update signature in {cl.file_path} to reflect new parameters and types.",
                        source_file=change.file_path,
                        doc_file=cl.file_path,
                        symbol_name=change.qualified_name,
                        line_number=cl.line_number,
                        confidence=0.90,
                    )
                )

    # 3. Undocumented Changes: Public breaking code changes or new symbols with zero doc coverage
    for change in symbol_changes:
        if change.symbol_name.startswith("_"):
            continue
        is_documented = (
            change.symbol_name in documented_symbols or change.qualified_name in documented_symbols
        )
        if not is_documented and change.change_kind in ("added", "signature_changed"):
            finding_id = _generate_id(
                "undocumented_change", change.file_path, None, change.qualified_name
            )
            findings.append(
                DriftFinding(
                    id=finding_id,
                    category="undocumented_change",
                    severity="warning" if change.breaking else "info",
                    title=f"Undocumented symbol '{change.qualified_name}'",
                    explanation=(
                        f"Symbol '{change.qualified_name}' was {change.change_kind} in {change.file_path}, "
                        f"but no corresponding documentation was found."
                    ),
                    remediation=f"Add documentation for '{change.qualified_name}' to repository docs.",
                    source_file=change.file_path,
                    doc_file=None,
                    symbol_name=change.qualified_name,
                    line_number=change.after.line_start if change.after else None,
                    confidence=0.75,
                )
            )

    crit = sum(1 for f in findings if f.severity == "critical")
    warn = sum(1 for f in findings if f.severity == "warning")
    info = sum(1 for f in findings if f.severity == "info")

    summary = (
        f"Found {len(findings)} documentation drift items ({crit} critical, {warn} warning, {info} info) "
        f"across {len(symbol_changes)} symbol changes and {len(claims)} documentation claims."
    )

    return DriftAnalysisReport(
        findings=findings,
        symbol_changes=symbol_changes,
        extracted_claims=claims,
        mappings=mappings,
        summary=summary,
        critical_count=crit,
        warning_count=warn,
        info_count=info,
    )
