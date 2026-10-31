"""Test helpers: build Stage 2 bundles and fake FileSources for Stage 3 tests."""

import hashlib
from dataclasses import dataclass, field

from docsentry.retrieval.classify import classify_path
from docsentry.retrieval.models import (
    ChangedFile,
    FileSnapshot,
    FileVersion,
    PullRequestBundle,
    PullRequestContext,
    RepositoryFileEntry,
    RepositoryFileIndex,
    SkippedFile,
)
from docsentry.retrieval.snapshots import FileReadResult

BASE_ORIG = "1" * 40
MERGE_BASE = "a" * 40
HEAD = "b" * 40


def blob(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


@dataclass
class FakeSource:
    by_sha: dict[str, dict[str, str]]
    oversized: set[str] = field(default_factory=set)
    reads: list[tuple[str, str]] = field(default_factory=list)

    def read(self, path: str, sha: str) -> FileReadResult:
        self.reads.append((path, sha))
        if path in self.oversized:
            return FileReadResult(
                skipped=SkippedFile(path=path, commit_sha=sha, reason="oversized", detail="big")
            )
        text = self.by_sha.get(sha, {}).get(path)
        if text is None:
            return FileReadResult(missing=True)
        return FileReadResult(
            version=FileVersion(
                path=path, commit_sha=sha, blob_sha=blob(text), size=len(text), text=text
            )
        )


def _index(sha: str, files: dict[str, str], complete: bool = True) -> RepositoryFileIndex:
    entries = [
        RepositoryFileEntry(
            path=p,
            type="blob",
            mode="100644",
            blob_sha=blob(t),
            size=len(t),
            commit_sha=sha,
            category=classify_path(p),
        )
        for p, t in sorted(files.items())
    ]
    return RepositoryFileIndex(commit_sha=sha, entries=entries, complete=complete)


def make_bundle(
    base: dict[str, str],
    head: dict[str, str],
    *,
    renames: dict[str, str] | None = None,
    seed_snapshots: bool = True,
    index_complete: bool = True,
    merge_base: str | None = MERGE_BASE,
) -> tuple[PullRequestBundle, FakeSource]:
    renames = renames or {}
    inverse = {v: k for k, v in renames.items()}
    changed: list[ChangedFile] = []
    snapshots: list[FileSnapshot] = []
    for path in sorted(set(head) | set(base)):
        prev = inverse.get(path)
        b_text = base.get(prev or path)
        h_text = head.get(path)
        if path in renames:  # base-only name handled via its head name
            continue
        if h_text is None and b_text is None:
            continue
        if prev is None and b_text == h_text:
            continue
        status = (
            "renamed"
            if prev
            else "added"
            if b_text is None
            else "removed"
            if h_text is None
            else "modified"
        )
        changed.append(
            ChangedFile(
                filename=path,
                previous_filename=prev,
                status=status,
                additions=1,
                deletions=1,
                changes=2,
                blob_sha=blob(h_text or ""),
                category=classify_path(path),
            )
        )
        if seed_snapshots and classify_path(path) in ("doc", "source"):
            before = (
                FileVersion(
                    path=prev or path,
                    commit_sha=MERGE_BASE,
                    blob_sha=blob(b_text),
                    size=len(b_text),
                    text=b_text,
                )
                if b_text is not None
                else None
            )
            after = (
                FileVersion(
                    path=path, commit_sha=HEAD, blob_sha=blob(h_text), size=len(h_text), text=h_text
                )
                if h_text is not None
                else None
            )
            snapshots.append(
                FileSnapshot(
                    path=path, previous_path=prev, status=status, before=before, after=after
                )
            )
    ctx = PullRequestContext(
        delivery_id="d1",
        installation_id=1,
        owner="o",
        repository="r",
        repository_id=7,
        pull_number=3,
        title="t",
        html_url="https://example.invalid/pr/3",
        base_ref="main",
        head_ref="feat",
        base_sha=BASE_ORIG,
        head_sha=HEAD,
        merge_base_sha=merge_base,
        state="open",
        is_draft=False,
        event_head_sha=HEAD,
    )
    bundle = PullRequestBundle(
        context=ctx,
        changed_files=changed,
        changed_files_complete=True,
        snapshots=snapshots,
        skipped_files=[],
        base_index=_index(MERGE_BASE, base, index_complete),
        head_index=_index(HEAD, head, index_complete),
        errors=[],
        retrieved_at="2026-01-01T00:00:00Z",
    )
    return bundle, FakeSource({MERGE_BASE: dict(base), HEAD: dict(head)})
