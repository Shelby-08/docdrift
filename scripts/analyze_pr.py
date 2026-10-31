#!/usr/bin/env python3
"""Deterministic documentation drift analysis CLI.

Usage:
    python scripts/analyze_pr.py --offline"""

import argparse
import json
import sys

from docsentry.intelligence.engine import analyze_bundle_drift
from docsentry.retrieval.models import (
    ChangedFile,
    FileSnapshot,
    FileVersion,
    PullRequestBundle,
    PullRequestContext,
    RepositoryFileEntry,
    RepositoryFileIndex,
)


def make_sample_bundle() -> PullRequestBundle:
    sha_base = "a" * 40
    sha_head = "b" * 40
    sha_blob = "1" * 40

    ctx = PullRequestContext(
        repo_id=101,
        repo_full_name="test-org/test-repo",
        pr_number=1,
        base_ref="main",
        base_sha=sha_base,
        head_ref="feature",
        head_sha=sha_head,
        head_repo_full_name="test-org/test-repo",
        head_repo_fork=False,
        is_cross_repository=False,
        merge_base_sha=sha_base,
        superseded_event=False,
    )

    changed = [
        ChangedFile(
            filename="docs/arch.md",
            status="modified",
            additions=5,
            deletions=1,
            changes=6,
            blob_sha=sha_blob,
            category="doc",
        ),
        ChangedFile(
            filename="src/core.py",
            status="modified",
            additions=10,
            deletions=2,
            changes=12,
            blob_sha=sha_blob,
            category="source",
        ),
    ]

    snapshots = [
        FileSnapshot(
            path="docs/arch.md",
            category="doc",
            base=FileVersion(
                path="docs/arch.md",
                commit_sha=sha_base,
                text="# Documentation\n\nUse `old_handler` for processing requests.\n",
                byte_size=55,
            ),
            head=FileVersion(
                path="docs/arch.md",
                commit_sha=sha_head,
                text="# Documentation\n\nUse `old_handler` for processing requests.\n",
                byte_size=55,
            ),
        ),
        FileSnapshot(
            path="src/core.py",
            category="source",
            base=FileVersion(
                path="src/core.py",
                commit_sha=sha_base,
                text="def old_handler(): pass\n",
                byte_size=24,
            ),
            head=FileVersion(
                path="src/core.py",
                commit_sha=sha_head,
                text="def new_handler(param: str): return param\n",
                byte_size=42,
            ),
        ),
    ]

    return PullRequestBundle(
        context=ctx,
        changed_files=changed,
        changed_files_complete=True,
        reported_changed_files=2,
        snapshots=snapshots,
        skipped_files=[],
        base_index=RepositoryFileIndex(commit_sha=sha_base, entries=[], complete=True, incomplete_reasons=[]),
        head_index=RepositoryFileIndex(commit_sha=sha_head, entries=[], complete=True, incomplete_reasons=[]),
        errors=[],
        warnings=[],
        retrieved_at="2026-11-01T00:00:00Z",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze PullRequestBundle drift")
    parser.add_argument("--offline", action="store_true", default=True, help="Run offline sample analysis")
    parser.parse_args()

    bundle = make_sample_bundle()
    report = analyze_bundle_drift(bundle)

    print("=== Drift Analysis Report ===")
    print(f"Summary: {report.summary}")
    print(f"Critical findings: {report.critical_count}")
    print(f"Warning findings: {report.warning_count}")
    print(f"Info findings: {report.info_count}")
    print("Findings details:")
    for f in report.findings:
        print(f"  [{f.severity.upper()}] {f.title}: {f.explanation}")
        print(f"    Remediation: {f.remediation}")


if __name__ == "__main__":
    main()
