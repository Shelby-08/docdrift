from docsentry.intelligence.engine import analyze_bundle_drift
from docsentry.retrieval.models import (
    FileSnapshot,
    FileVersion,
    PullRequestBundle,
    PullRequestContext,
    RepositoryFileIndex,
)

SHA_BASE = "a" * 40
SHA_HEAD = "b" * 40


def test_engine_analyze_bundle_drift() -> None:
    ctx = PullRequestContext(
        repo_id=1,
        repo_full_name="org/repo",
        pr_number=1,
        base_ref="main",
        base_sha=SHA_BASE,
        head_ref="feat",
        head_sha=SHA_HEAD,
        head_repo_full_name="org/repo",
        head_repo_fork=False,
        is_cross_repository=False,
        merge_base_sha=SHA_BASE,
    )

    src_base = "def calculate(x: int) -> int: return x\n"
    src_head = "def calculate(x: int, y: int) -> int: return x + y\n"
    doc_head = "# Guide\n\nCall `calculate(x)` to process.\n"

    snapshots = [
        FileSnapshot(
            path="src/calc.py",
            category="source",
            base=FileVersion(path="src/calc.py", commit_sha=SHA_BASE, text=src_base, byte_size=len(src_base)),
            head=FileVersion(path="src/calc.py", commit_sha=SHA_HEAD, text=src_head, byte_size=len(src_head)),
        ),
        FileSnapshot(
            path="docs/guide.md",
            category="doc",
            base=FileVersion(path="docs/guide.md", commit_sha=SHA_BASE, text=doc_head, byte_size=len(doc_head)),
            head=FileVersion(path="docs/guide.md", commit_sha=SHA_HEAD, text=doc_head, byte_size=len(doc_head)),
        ),
    ]

    bundle = PullRequestBundle(
        context=ctx,
        changed_files=[],
        changed_files_complete=True,
        reported_changed_files=2,
        snapshots=snapshots,
        skipped_files=[],
        base_index=RepositoryFileIndex(commit_sha=SHA_BASE, entries=[], complete=True, incomplete_reasons=[]),
        head_index=RepositoryFileIndex(commit_sha=SHA_HEAD, entries=[], complete=True, incomplete_reasons=[]),
        errors=[],
        warnings=[],
        retrieved_at="2026-11-01T00:00:00Z",
    )

    report = analyze_bundle_drift(bundle)
    assert len(report.findings) >= 1
    assert any(f.category == "broken_contract" for f in report.findings)
