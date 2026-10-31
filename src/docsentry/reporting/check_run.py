"""Pure Check Run payload builder: AnalysisResult (+ optional AIReviewResult) -> report."""

from collections.abc import Sequence
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from docsentry.ai_review.models import AIReviewResult
from docsentry.intelligence.models.analysis import AnalysisResult
from docsentry.intelligence.models.common import Side
from docsentry.intelligence.models.findings import (
    DriftFinding,
    EvidenceStatus,
    Severity,
    TemporalStatus,
)

SUMMARY_CAP = 30_000
TEXT_CAP = 300
_SPECIALS = set("\\`*_{}[]()#+-.!|~")
_SEV = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2, Severity.INFO: 3}
_EV = {EvidenceStatus.CONFIRMED: 0, EvidenceStatus.POTENTIAL: 1}


class CheckAnnotation(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    start_line: int
    end_line: int
    annotation_level: Literal["notice", "warning"]
    title: str
    message: str


class CheckRunReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    summary: str
    conclusion: Literal["success", "neutral"]
    annotations: tuple[CheckAnnotation, ...] = ()
    omitted_annotations: int = 0
    new_findings: int = 0


def esc(text: str, cap: int = TEXT_CAP) -> str:
    """Escape repo/model text for Markdown: one line, no HTML, no autolinks, bounded."""
    flat = " ".join(text.split())
    if len(flat) > cap:
        flat = flat[: cap - 1].rstrip() + "…"
    flat = flat.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    flat = flat.replace("://", ":&#47;&#47;").replace("@", "&#64;")
    return "".join("\\" + c if c in _SPECIALS else c for c in flat)


def permalink(owner: str, repo: str, sha: str, path: str, line: int | None) -> str | None:
    if not path or path.startswith("/") or ".." in path.split("/") or "\\" in path:
        return None
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha.lower()):
        return None
    anchor = f"#L{line}" if isinstance(line, int) and line > 0 else ""
    return f"https://github.com/{quote(owner)}/{quote(repo)}/blob/{sha}/{quote(path)}{anchor}"


def _is_new(f: DriftFinding) -> bool:
    return f.temporal_status == TemporalStatus.NEWLY_INTRODUCED and f.evidence_status in _EV


def _order(f: DriftFinding) -> tuple[int, int, str, int, str]:
    return (
        _SEV[f.severity],
        _EV.get(f.evidence_status, 9),
        f.documentation_file,
        f.documentation_line or 0,
        f.finding_id,
    )


def _code_link(res: AnalysisResult, f: DriftFinding) -> str:
    if not f.code_file:
        return "no code location"
    side = Side.HEAD
    for ev in f.evidence:
        if ev.kind == "code_fact" and ev.side is not None:
            side = ev.side
            break
    sha = res.context.head_sha if side == Side.HEAD else res.context.base_sha
    url = permalink(res.context.owner, res.context.repository, sha, f.code_file, f.code_line)
    label = esc(f"{f.code_file}:{f.code_line}" if f.code_line else f.code_file, 200)
    return f"[{label}]({url})" if url else label


def _doc_span(res: AnalysisResult, f: DriftFinding) -> int | None:
    """End line of the head-side claim covering the finding's doc line, else None."""
    line = f.documentation_line
    if line is None:
        return None
    ends = [
        c.end_line
        for c in res.claims
        if c.path == f.documentation_file and c.line <= line <= c.end_line
    ]
    return max(ends) if ends else None


def _annotations(
    res: AnalysisResult, new: Sequence[DriftFinding], cap: int
) -> tuple[tuple[CheckAnnotation, ...], int]:
    grouped: dict[tuple[str, int], list[DriftFinding]] = {}
    for f in new:
        if f.documentation_line is not None and _doc_span(res, f) is not None:
            grouped.setdefault((f.documentation_file, f.documentation_line), []).append(f)
    out: list[CheckAnnotation] = []
    for (path, line), fs in sorted(grouped.items(), key=lambda kv: _order(kv[1][0])):
        end = _doc_span(res, fs[0]) or line
        confirmed = any(x.evidence_status == EvidenceStatus.CONFIRMED for x in fs)
        level: Literal["notice", "warning"] = "warning" if confirmed else "notice"
        parts = [esc(x.description, 250) + " Code: " + _code_link(res, x) for x in fs[:3]]
        out.append(
            CheckAnnotation(
                path=path,
                start_line=line,
                end_line=max(end, line),
                annotation_level=level,
                title=f"Documentation drift ({fs[0].rule_id})"[:255],
                message=" | ".join(parts)[:1500],
            )
        )
    return tuple(out[:cap]), max(0, len(out) - cap)


def _ai_section(ai: AIReviewResult | None) -> list[str]:
    if ai is None:
        return []
    status = f"Status: `{ai.status.value}`"
    if ai.error_code:
        status += f" ({esc(ai.error_code, 60)})"
    lines = ["", "### AI-assisted interpretation (advisory only)", status]
    for a in ai.assessments:
        refs = ", ".join(esc(e, 40) for e in a.evidence_ids) or "none"
        lines.append(
            f"- {esc(a.item_id, 80)}: **{a.verdict.value}**, evidence: {refs}. "
            f"{esc(a.explanation, 500)}"
        )
    if ai.assessments:
        lines.append("_AI output is advisory. It never changes deterministic findings._")
    return lines


def build_report(
    res: AnalysisResult,
    ai: AIReviewResult | None = None,
    *,
    max_annotations: int = 25,
    max_summary_findings: int = 30,
) -> CheckRunReport:
    new = sorted((f for f in res.findings if _is_new(f)), key=_order)
    other = sorted((f for f in res.findings if not _is_new(f)), key=_order)
    conclusion: Literal["success", "neutral"] = "success" if res.complete and not new else "neutral"
    if new:
        title = f"{len(new)} newly introduced documentation drift finding(s)"
    elif not res.complete:
        title = "Analysis incomplete: no new drift found in analysed files"
    else:
        title = "No new documentation drift"
    lines = [f"## DocSentry: {esc(title, 200)}", ""]
    state = "complete" if res.complete else "PARTIAL"
    lines.append(f"New: {len(new)} | Other findings: {len(other)} | Analysis: {state}")
    if new:
        lines += ["", "### Newly introduced findings"]
        for f in new[:max_summary_findings]:
            doc_url = permalink(
                res.context.owner,
                res.context.repository,
                res.context.head_sha,
                f.documentation_file,
                f.documentation_line,
            )
            doc_lbl = esc(f"{f.documentation_file}:{f.documentation_line or '?'}", 200)
            doc = f"[{doc_lbl}]({doc_url})" if doc_url else doc_lbl
            lines.append(
                f"- **{f.evidence_status.value}** / {f.severity.value} / `{f.rule_id}` "
                f'{doc}: "{esc(f.affected_text)}". {esc(f.description, 300)} '
                f"Code: {_code_link(res, f)}"
            )
        if len(new) > max_summary_findings:
            lines.append(f"- … {len(new) - max_summary_findings} more not shown")
    if other:
        lines += [
            "",
            "<details><summary>Other findings (context only, not annotated)</summary>",
            "",
        ]
        for f in other[:max_summary_findings]:
            where = esc(f"{f.documentation_file}:{f.documentation_line or '?'}", 200)
            lines.append(
                f"- {f.temporal_status.value} / {f.evidence_status.value} {where}: "
                f"{esc(f.description, 200)}"
            )
        if len(other) > max_summary_findings:
            lines.append(f"- … {len(other) - max_summary_findings} more not shown")
        lines += ["", "</details>"]
    lines += _ai_section(ai)
    lines += ["", "### Coverage and limitations"]
    reasons = f" ({esc(', '.join(res.incomplete_reasons), 300)})" if res.incomplete_reasons else ""
    lines.append(f"- Complete: {res.complete}{reasons}")
    by_reason: dict[str, int] = {}
    for s in res.skipped_files:
        by_reason[s.reason] = by_reason.get(s.reason, 0) + 1
    if by_reason:
        lines.append(
            "- Skipped files: "
            + ", ".join(f"{esc(k, 40)}={v}" for k, v in sorted(by_reason.items()))
        )
    if res.ai_review_input.omitted_count:
        lines.append(f"- AI review items omitted by limit: {res.ai_review_input.omitted_count}")
    anns, omitted = _annotations(res, new, max_annotations)
    if omitted:
        lines.append(f"- Annotations omitted by limit: {omitted}")
    lines.append("- Deterministic analysis is authoritative. Python source and Markdown only.")
    summary = "\n".join(lines)
    if len(summary) > SUMMARY_CAP:
        cut = summary[: SUMMARY_CAP - 80].rsplit("\n", 1)[0]
        summary = cut + "\n\n_Summary truncated to fit GitHub limits._"
    return CheckRunReport(
        title=title[:250],
        summary=summary,
        conclusion=conclusion,
        annotations=anns,
        omitted_annotations=omitted,
        new_findings=len(new),
    )
