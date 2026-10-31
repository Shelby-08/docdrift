"""Loads base/head RepoSnapshots from a Stage 2 bundle. The ONLY module touching Stage 2."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from docsentry.intelligence.code_analysis.language_registry import get_adapter
from docsentry.intelligence.code_analysis.symbol_index import resolve_import
from docsentry.intelligence.models.common import (
    AnalysisLimits,
    FileClass,
    Side,
    SkippedAnalysisFile,
    SkippedReason,
)
from docsentry.intelligence.repository.file_classifier import classify_file
from docsentry.intelligence.repository.snapshot import RepoSnapshot
from docsentry.retrieval.models import PullRequestBundle, SkippedFile
from docsentry.retrieval.snapshots import FileReadResult

_MAX_UNSUPPORTED_RECORDED = 200
_REASON_MAP: dict[str, SkippedReason] = {
    "oversized": "oversized",
    "binary": "binary",
    "not_utf8": "not_utf8",
    "over_budget": "over_budget",
    "missing": "missing",
}


class FileSource(Protocol):
    def read(self, path: str, sha: str) -> FileReadResult: ...


@dataclass
class _SideState:
    sha: str
    paths: set[str] = field(default_factory=set)
    files: dict[str, str] = field(default_factory=dict)
    blobs: dict[str, str] = field(default_factory=dict)
    index_blobs: dict[str, str] = field(default_factory=dict)
    skipped: list[SkippedAnalysisFile] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _doc_priority(path: str) -> tuple[int, str]:
    low = path.lower()
    first = 0 if low.startswith("docs/") or low.split("/")[-1].startswith("readme") else 1
    return first, path


def load_snapshots(
    bundle: PullRequestBundle,
    source: FileSource,
    limits: AnalysisLimits,
    monotonic: Callable[[], float] = time.monotonic,
    started: float | None = None,
) -> tuple[RepoSnapshot, RepoSnapshot]:
    t0 = monotonic() if started is None else started
    ctx = bundle.context
    base_sha = ctx.merge_base_sha or ctx.base_sha
    base = _SideState(base_sha)
    head = _SideState(ctx.head_sha)
    shared_reasons: list[str] = []
    if ctx.merge_base_sha is None:
        shared_reasons.append("merge_base_unresolved")
    if not bundle.changed_files_complete:
        shared_reasons.append("changed_files_incomplete")
    if not bundle.base_index.complete:
        base.reasons.append("base_index_incomplete")
    if not bundle.head_index.complete:
        head.reasons.append("head_index_incomplete")
    if any(e.code != "warning" for e in bundle.errors):
        shared_reasons.append("retrieval_errors")

    for state, index in ((base, bundle.base_index), (head, bundle.head_index)):
        for entry in index.entries:
            if entry.type == "blob":
                state.paths.add(entry.path)
                state.index_blobs[entry.path] = entry.blob_sha

    changed_names: set[str] = set()
    for cf in bundle.changed_files:
        changed_names.add(cf.filename)
        head.paths.add(cf.filename) if cf.status != "removed" else None
        if cf.previous_filename:
            changed_names.add(cf.previous_filename)
            base.paths.add(cf.previous_filename)
        elif cf.status != "added":
            base.paths.add(cf.filename)

    # Seed from Stage 2 snapshots (no refetch).
    for snap in bundle.snapshots:
        if snap.before is not None:
            base.files[snap.before.path] = snap.before.text
            base.blobs[snap.before.path] = snap.before.blob_sha
        if snap.after is not None:
            head.files[snap.after.path] = snap.after.text
            head.blobs[snap.after.path] = snap.after.blob_sha
    for sf in bundle.skipped_files:
        _record_stage2_skip(sf, base, head)

    out_of_time = False

    def timed_out() -> bool:
        nonlocal out_of_time
        if monotonic() - t0 > limits.time_budget_seconds:
            out_of_time = True
        return out_of_time

    def load(state: _SideState, path: str) -> bool:
        if path in state.files:
            return True
        if timed_out():
            state.skipped.append(
                SkippedAnalysisFile(path=path, side=_side(state, base), reason="time_budget")
            )
            return False
        res = source.read(path, state.sha)
        if res.version is not None:
            state.files[path] = res.version.text
            state.blobs[path] = res.version.blob_sha
            return True
        side = _side(state, base)
        if res.skipped is not None:
            reason = _REASON_MAP.get(res.skipped.reason, "other")
            state.skipped.append(
                SkippedAnalysisFile(path=path, side=side, reason=reason, detail=res.skipped.detail)
            )
        elif res.missing:
            state.skipped.append(SkippedAnalysisFile(path=path, side=side, reason="missing"))
        return False

    docs_loaded = 0
    sources_loaded = 0

    # 1. changed docs and changed python sources
    for cf in sorted(bundle.changed_files, key=lambda f: f.filename):
        cls = classify_file(cf.filename)
        if cls == FileClass.UNSUPPORTED:
            continue
        if cls == FileClass.TEST:
            for st, p in ((head, cf.filename), (base, cf.previous_filename or cf.filename)):
                if _exists(cf.status, st is head):
                    st.skipped.append(
                        SkippedAnalysisFile(path=p, side=_side(st, base), reason="test_file")
                    )
            continue
        if cls not in (FileClass.DOC, FileClass.SOURCE):
            continue
        if cls == FileClass.DOC:
            if docs_loaded >= limits.max_doc_files:
                head.skipped.append(
                    SkippedAnalysisFile(path=cf.filename, side=Side.HEAD, reason="over_budget")
                )
                continue
            docs_loaded += 1
        else:
            if sources_loaded >= limits.max_source_files:
                head.skipped.append(
                    SkippedAnalysisFile(path=cf.filename, side=Side.HEAD, reason="over_budget")
                )
                continue
            sources_loaded += 1
        if cf.status != "removed":
            load(head, cf.filename)
        if cf.status != "added":
            load(base, cf.previous_filename or cf.filename)

    # 2. unchanged docs from the index
    unchanged_docs = sorted(
        (p for p in head.paths if p not in changed_names and classify_file(p) == FileClass.DOC),
        key=_doc_priority,
    )
    for path in unchanged_docs:
        if docs_loaded >= limits.max_doc_files:
            head.skipped.append(
                SkippedAnalysisFile(path=path, side=Side.HEAD, reason="over_budget")
            )
            continue
        docs_loaded += 1
        if load(head, path):
            same = base.index_blobs.get(path) is not None and base.index_blobs.get(
                path
            ) == head.index_blobs.get(path)
            if same:
                base.files[path] = head.files[path]
                base.blobs[path] = head.blobs.get(path, "")
            elif path in base.paths:
                load(base, path)

    # 3. unchanged python sources: imported by changed sources first, then fill the cap
    py_unchanged = sorted(
        p
        for p in head.paths
        if p not in changed_names
        and classify_file(p) == FileClass.SOURCE
        and get_adapter(p) is not None
    )
    wanted = _imported_paths(head, base, frozenset(head.paths | base.paths), py_unchanged)
    ordered = wanted + [p for p in py_unchanged if p not in wanted]
    for path in ordered[: limits.max_unchanged_source_files]:
        if load(head, path):
            same = base.index_blobs.get(path) is not None and base.index_blobs.get(
                path
            ) == head.index_blobs.get(path)
            if same:
                base.files[path] = head.files[path]
                base.blobs[path] = head.blobs.get(path, "")
            elif path in base.paths:
                load(base, path)
    scan_complete_head = True
    for path in ordered[limits.max_unchanged_source_files :]:
        scan_complete_head = False
        head.skipped.append(SkippedAnalysisFile(path=path, side=Side.HEAD, reason="over_budget"))

    # unsupported / test files present in indexes
    recorded = 0
    for state in (head, base):
        for path in sorted(state.paths):
            cls = classify_file(path)
            if cls == FileClass.UNSUPPORTED and recorded < _MAX_UNSUPPORTED_RECORDED:
                recorded += 1
                reason: SkippedReason = (
                    "unsupported_doc_format"
                    if path.lower().endswith((".mdx", ".rst", ".adoc", ".asciidoc"))
                    else "unsupported_language"
                )
                state.skipped.append(
                    SkippedAnalysisFile(path=path, side=_side(state, base), reason=reason)
                )

    return (
        _finish(base, base, shared_reasons, out_of_time, True),
        _finish(head, base, shared_reasons, out_of_time, scan_complete_head),
    )


def _side(state: _SideState, base: _SideState) -> Side:
    return Side.BASE if state is base else Side.HEAD


def _exists(status: str, is_head: bool) -> bool:
    return (status != "removed") if is_head else (status != "added")


def _record_stage2_skip(sf: SkippedFile, base: _SideState, head: _SideState) -> None:
    if sf.reason == "unsupported_type":
        return  # classified by the Stage 3 classifier instead
    state = base if sf.commit_sha == base.sha else head
    reason = _REASON_MAP.get(sf.reason, "other")
    state.skipped.append(
        SkippedAnalysisFile(
            path=sf.path,
            side=Side.BASE if state is base else Side.HEAD,
            reason=reason,
            detail=sf.detail or sf.reason,
        )
    )


def _imported_paths(
    head: _SideState, base: _SideState, all_paths: frozenset[str], candidates: list[str]
) -> list[str]:
    from docsentry.intelligence.code_analysis.python_parser import parse_python

    cand = set(candidates)
    found: set[str] = set()
    for state in (head, base):
        for path, text in sorted(state.files.items()):
            if get_adapter(path) is None:
                continue
            parsed = parse_python(path, text, state.sha)
            for rec in parsed.imports:
                target = resolve_import(path, rec, all_paths)
                if target and target in cand:
                    found.add(target)
    return sorted(found)


def _finish(
    state: _SideState,
    base: _SideState,
    shared: list[str],
    out_of_time: bool,
    scan_complete: bool,
) -> RepoSnapshot:
    reasons = list(dict.fromkeys([*shared, *state.reasons]))
    counted = [s for s in state.skipped if s.reason != "test_file"]
    if counted:
        reasons.append(f"skipped_files:{len(counted)}")
    if out_of_time:
        reasons.append("time_budget")
    python_unloaded = any(
        p not in state.files and classify_file(p) == FileClass.SOURCE and get_adapter(p) is not None
        for p in state.paths
    )
    skipped = tuple(
        sorted(
            {(s.path, s.side.value, s.reason): s for s in state.skipped}.values(),
            key=lambda s: (s.path, s.side.value, s.reason),
        )
    )
    all_paths = set(state.paths) | set(state.files)
    return RepoSnapshot(
        commit_sha=state.sha,
        files=dict(state.files),
        paths=frozenset(all_paths),
        complete=not reasons,
        incomplete_reasons=tuple(reasons),
        skipped=skipped,
        blob_shas=dict(state.blobs),
        source_index_complete="head_index_incomplete" not in state.reasons
        and "base_index_incomplete" not in state.reasons,
        source_scan_complete=scan_complete and not python_unloaded and not out_of_time,
    )
