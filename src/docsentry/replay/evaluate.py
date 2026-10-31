"""Evaluation harness: path/line recall and noise metrics on historical commits."""

import json
import statistics
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from docsentry.intelligence.models.findings import DriftFinding, EvidenceStatus, TemporalStatus
from docsentry.replay.git_source import Git, GitError, changed_doc_lines
from docsentry.replay.runner import analyze_local


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["drift", "control"]
    repo_path: str
    base: str
    code_commit: str
    doc_fix_commit: str | None = None


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[Case]


def load_manifest(text: str) -> Manifest:
    data = json.loads(text)
    return Manifest.model_validate({"cases": data} if isinstance(data, list) else data)


def new_findings(findings: tuple[DriftFinding, ...]) -> list[DriftFinding]:
    return [
        f
        for f in findings
        if f.temporal_status == TemporalStatus.NEWLY_INTRODUCED
        and f.evidence_status in (EvidenceStatus.CONFIRMED, EvidenceStatus.POTENTIAL)
    ]


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def evaluate_case(case: Case) -> dict[str, Any]:
    row: dict[str, Any] = {"id": case.id, "kind": case.kind}
    try:
        git = Git(case.repo_path)
        res = analyze_local(case.repo_path, case.base, case.code_commit, git=git)
        found = new_findings(res.findings)
        row.update(
            findings=len(found),
            categories=sorted({f.category.value for f in found}),
            complete=res.complete,
            path_hit=None,
            line_hit=None,
            line_match="not_applicable",
            error=None,
        )
        if case.kind == "drift" and case.doc_fix_commit:
            fix = git.resolve(case.doc_fix_commit)
            code_sha = git.resolve(case.code_commit)
            ranges = changed_doc_lines(git, fix)
            row["path_hit"] = any(f.documentation_file in ranges for f in found)
            computable: list[bool] = []
            hit = False
            for f in found:
                if f.documentation_file not in ranges or f.documentation_line is None:
                    continue
                same = git.blob_sha(code_sha, f.documentation_file) == git.blob_sha(
                    f"{fix}^", f.documentation_file
                )
                computable.append(same)
                if same and any(
                    _overlap((f.documentation_line, f.documentation_line), r)
                    for r in ranges[f.documentation_file]
                ):
                    hit = True
            if computable and all(computable):
                row["line_hit"], row["line_match"] = hit, "computed"
            else:
                row["line_match"] = "unavailable"
    except GitError as exc:
        row.update(
            findings=0,
            categories=[],
            complete=False,
            path_hit=None,
            line_hit=None,
            line_match="unavailable",
            error=exc.code,
        )
    return row


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    drift = [
        r for r in rows if r["kind"] == "drift" and r["error"] is None and r["path_hit"] is not None
    ]
    line = [r for r in drift if r["line_hit"] is not None]
    controls = [r for r in rows if r["kind"] == "control"]
    counts = [r["findings"] for r in rows]
    return {
        "cases": len(rows),
        "drift_cases_with_fix": len(drift),
        "path_recall": (sum(1 for r in drift if r["path_hit"]) / len(drift)) if drift else None,
        "line_recall": (sum(1 for r in line if r["line_hit"]) / len(line)) if line else None,
        "line_computable_cases": len(line),
        "median_findings_per_case": statistics.median(counts) if counts else None,
        "max_findings_per_case": max(counts) if counts else None,
        "control_cases": len(controls),
        "findings_per_control_case": [r["findings"] for r in controls],
        "errors": sum(1 for r in rows if r["error"]),
    }


def evaluate(manifest: Manifest) -> dict[str, Any]:
    rows = [evaluate_case(c) for c in manifest.cases]
    return {"cases": rows, "aggregates": aggregate(rows)}


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def to_markdown(report: dict[str, Any]) -> str:
    lines = [
        "| case | kind | findings | categories | path hit | line hit | line match | error |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report["cases"]:
        lines.append(
            f"| {r['id']} | {r['kind']} | {r['findings']} | {','.join(r['categories']) or '-'} | "
            f"{r['path_hit']} | {r['line_hit']} | {r['line_match']} | {r['error'] or '-'} |"
        )
    a = report["aggregates"]
    lines += [
        "",
        f"- Path recall: {_pct(a['path_recall'])} ({a['drift_cases_with_fix']} drift cases)",
        f"- Line recall: {_pct(a['line_recall'])} ({a['line_computable_cases']} computable)",
        f"- Median / max findings: {a['median_findings_per_case']} / {a['max_findings_per_case']}",
        f"- Findings per control case: {a['findings_per_control_case']}",
    ]
    return "\n".join(lines)
