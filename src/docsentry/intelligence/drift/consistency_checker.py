"""Temporal classification of base/head consistency records into findings."""

import hashlib
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from docsentry.intelligence.models.common import ConsistencyState, Exposure, Side
from docsentry.intelligence.models.findings import (
    ConsistencyRecord,
    DriftFinding,
    Evidence,
    EvidenceStatus,
    Severity,
    TemporalStatus,
)


@dataclass
class TemporalStats:
    no_drift: int = 0
    untouched_pairs: int = 0
    by_evidence_status: Counter[str] = field(default_factory=Counter)
    by_temporal_status: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, object]:
        return {
            "no_drift": self.no_drift,
            "untouched_pairs": self.untouched_pairs,
            "by_evidence_status": dict(sorted(self.by_evidence_status.items())),
            "by_temporal_status": dict(sorted(self.by_temporal_status.items())),
        }


def severity_for(status: EvidenceStatus, exposure: Exposure) -> Severity:
    public = exposure == Exposure.PUBLIC
    if status == EvidenceStatus.CONFIRMED:
        return Severity.HIGH if public else Severity.MEDIUM
    if status == EvidenceStatus.POTENTIAL:
        return Severity.MEDIUM if public else Severity.LOW
    return Severity.INFO


def _introduced(temporal: TemporalStatus) -> bool | None:
    if temporal == TemporalStatus.NEWLY_INTRODUCED:
        return True
    if temporal in (TemporalStatus.PRE_EXISTING, TemporalStatus.RESOLVED):
        return False
    return None


def _make_finding(
    base: ConsistencyRecord | None,
    head: ConsistencyRecord | None,
    temporal: TemporalStatus,
) -> DriftFinding:
    primary = head if head is not None and head.state != ConsistencyState.CONSISTENT else base
    if primary is None:
        primary = head
    assert primary is not None
    doc_rec = head or base
    assert doc_rec is not None
    code_rec = head if head is not None and head.code_provenance is not None else base
    code_prov = code_rec.code_provenance if code_rec else None
    if code_prov is None and primary.code_provenance is not None:
        code_prov = primary.code_provenance
    evidence: list[Evidence] = []
    seen: set[tuple[str, str | None, str]] = set()
    for rec in (head, base):
        if rec is None:
            continue
        for ev in rec.evidence:
            marker = (ev.kind, ev.side.value if ev.side else None, ev.description)
            if marker not in seen:
                seen.add(marker)
                evidence.append(ev)
    evidence.append(
        Evidence(
            kind="temporal",
            description=(
                f"base={base.state.value if base else 'absent'}, "
                f"head={head.state.value if head else 'absent'} -> {temporal.value}"
            ),
        )
    )
    old_value = doc_rec.doc_value
    new_value = (head.code_value if head is not None else None) if head else None
    if new_value is None and base is not None:
        new_value = base.code_value
    reasons = tuple(dict.fromkeys([*primary.reasons, *primary.mapping_reasons]))
    status = primary.evidence_status
    key = primary.key
    return DriftFinding(
        finding_id=hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
        rule_id=primary.rule_id,
        category=primary.category,
        evidence_status=status,
        temporal_status=temporal,
        severity=severity_for(status, primary.exposure),
        description=primary.summary,
        documentation_file=doc_rec.claim.path,
        documentation_line=doc_rec.claim.line,
        affected_text=doc_rec.claim.original_text[:500],
        code_file=code_prov.path if code_prov else None,
        code_line=code_prov.line if code_prov else None,
        old_value=old_value,
        new_value=new_value,
        suggested_correction=primary.suggested_correction,
        evidence=tuple(evidence),
        mapping_reasons=reasons,
        requires_ai_review=primary.requires_ai_review
        or status != EvidenceStatus.CONFIRMED
        or temporal == TemporalStatus.INDETERMINATE,
        introduced_by_current_pr=_introduced(temporal),
        key=key,
    )


def classify_temporal_ex(
    base_records: Mapping[str, ConsistencyRecord],
    head_records: Mapping[str, ConsistencyRecord],
    touched: Callable[[str], bool],
) -> tuple[list[DriftFinding], TemporalStats]:
    stats = TemporalStats()
    findings: list[DriftFinding] = []

    def emit(b: ConsistencyRecord | None, h: ConsistencyRecord | None, t: TemporalStatus) -> None:
        f = _make_finding(b, h, t)
        findings.append(f)
        stats.by_evidence_status[f.evidence_status.value] += 1
        stats.by_temporal_status[f.temporal_status.value] += 1

    for key in sorted(set(base_records) | set(head_records)):
        b = base_records.get(key)
        h = head_records.get(key)
        bs = b.state if b else None
        hs = h.state if h else None
        if hs is None:
            if bs == ConsistencyState.INCONSISTENT and touched(key):
                emit(b, None, TemporalStatus.RESOLVED)
            continue
        if hs == ConsistencyState.CONSISTENT:
            if bs == ConsistencyState.INCONSISTENT:
                emit(b, h, TemporalStatus.RESOLVED)
            else:
                stats.no_drift += 1
            continue
        if hs == ConsistencyState.INCONSISTENT:
            if bs == ConsistencyState.CONSISTENT:
                emit(b, h, TemporalStatus.NEWLY_INTRODUCED)
            elif bs == ConsistencyState.INCONSISTENT:
                if touched(key):
                    emit(b, h, TemporalStatus.PRE_EXISTING)
                else:
                    stats.untouched_pairs += 1
            elif touched(key):
                emit(b, h, TemporalStatus.NEWLY_INTRODUCED)
            else:
                emit(b, h, TemporalStatus.INDETERMINATE)
            continue
        # head not evaluable
        if touched(key):
            emit(b, h, TemporalStatus.INSUFFICIENT_EVIDENCE)
        else:
            stats.untouched_pairs += 1
    return findings, stats


def classify_temporal(
    base_records: Mapping[str, ConsistencyRecord],
    head_records: Mapping[str, ConsistencyRecord],
    touched: Callable[[str], bool],
) -> list[DriftFinding]:
    return classify_temporal_ex(base_records, head_records, touched)[0]


__all__ = ["Side", "TemporalStats", "classify_temporal", "classify_temporal_ex", "severity_for"]
