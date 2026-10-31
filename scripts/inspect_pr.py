#!/usr/bin/env python3
"""Offline and live verification script for Stage 2 PullRequestBundle.

Usage:
    python scripts/inspect_pr.py --offline
    python scripts/inspect_pr.py --repo owner/name --pr 1"""

import argparse
import json
import sys
from typing import Any

from docsentry.config import load_settings
from docsentry.models import PullRequestEventContext
from docsentry.retrieval.auth import GitHubAuthService
from docsentry.retrieval.bundle_builder import build_pull_request_bundle
from docsentry.retrieval.models import (
    ChangedFile,
    FileSnapshot,
    FileVersion,
    PullRequestBundle,
    PullRequestContext,
    RepositoryFileEntry,
    RepositoryFileIndex,
)


def make_offline_bundle() -> PullRequestBundle:
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
            additions=10,
            deletions=2,
            changes=12,
            blob_sha=sha_blob,
            category="doc",
        ),
        ChangedFile(
            filename="src/core.py",
            status="modified",
            additions=5,
            deletions=1,
            changes=6,
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
                text="# Arch\n\nOld documentation.",
                byte_size=23,
            ),
            head=FileVersion(
                path="docs/arch.md",
                commit_sha=sha_head,
                text="# Arch\n\nNew updated documentation.",
                byte_size=31,
            ),
        ),
        FileSnapshot(
            path="src/core.py",
            category="source",
            base=FileVersion(
                path="src/core.py",
                commit_sha=sha_base,
                text="def run(): pass\n",
                byte_size=16,
            ),
            head=FileVersion(
                path="src/core.py",
                commit_sha=sha_head,
                text="def run(): return True\n",
                byte_size=23,
            ),
        ),
    ]

    base_idx = RepositoryFileIndex(
        commit_sha=sha_base,
        entries=[
            RepositoryFileEntry(
                path="docs/arch.md",
                type="blob",
                mode="100644",
                blob_sha=sha_blob,
                commit_sha=sha_base,
                size=23,
                category="doc",
            ),
            RepositoryFileEntry(
                path="src/core.py",
                type="blob",
                mode="100644",
                blob_sha=sha_blob,
                commit_sha=sha_base,
                size=16,
                category="source",
            ),
        ],
        complete=True,
        incomplete_reasons=[],
    )

    head_idx = RepositoryFileIndex(
        commit_sha=sha_head,
        entries=[
            RepositoryFileEntry(
                path="docs/arch.md",
                type="blob",
                mode="100644",
                blob_sha=sha_blob,
                commit_sha=sha_head,
                size=31,
                category="doc",
            ),
            RepositoryFileEntry(
                path="src/core.py",
                type="blob",
                mode="100644",
                blob_sha=sha_blob,
                commit_sha=sha_head,
                size=23,
                category="source",
            ),
        ],
        complete=True,
        incomplete_reasons=[],
    )

    return PullRequestBundle(
        context=ctx,
        changed_files=changed,
        changed_files_complete=True,
        reported_changed_files=2,
        snapshots=snapshots,
        skipped_files=[],
        base_index=base_idx,
        head_index=head_idx,
        errors=[],
        warnings=[],
        retrieved_at="2026-11-01T00:00:00Z",
    )


def inspect_bundle(bundle: PullRequestBundle) -> dict[str, Any]:
    return {
        "pr_number": bundle.context.pr_number,
        "repo": bundle.context.repo_full_name,
        "base_sha": bundle.context.base_sha,
        "head_sha": bundle.context.head_sha,
        "merge_base_sha": bundle.context.merge_base_sha,
        "changed_files_count": len(bundle.changed_files),
        "snapshots_count": len(bundle.snapshots),
        "skipped_files_count": len(bundle.skipped_files),
        "base_index_entries": len(bundle.base_index.entries),
        "head_index_entries": len(bundle.head_index.entries),
        "errors": [e.model_dump() for e in bundle.errors],
        "warnings": bundle.warnings,
        "retrieved_at": bundle.retrieved_at,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect PullRequestBundle")
    parser.add_argument("--offline", action="store_true", help="Run offline synthetic check")
    parser.add_argument("--repo", type="str", help="owner/name")
    parser.add_argument("--pr", type=int, help="PR number")
    parser.add_argument("--installation-id", type=int, default=1, help="GitHub App installation ID")
    args = parser.parse_args()

    if args.offline or not (args.repo and args.pr):
        bundle = make_offline_bundle()
        summary = inspect_bundle(bundle)
        print("=== PullRequestBundle Offline Verification ===")
        print(json.dumps(summary, indent=2))
        sys.exit(0)

    # Live check
    settings = load_settings()
    auth = GitHubAuthService(settings)
    client = auth.client_for_installation(args.installation_id)
    parts = args.repo.split("/")
    if len(parts) != 2:
        print("Error: --repo must be in owner/repo format", file=sys.stderr)
        sys.exit(1)
    owner, repo_name = parts

    event = PullRequestEventContext(
        action="synchronize",
        owner=owner,
        repo=repo_name,
        repo_id=0,
        installation_id=args.installation_id,
        pr_number=args.pr,
        base_sha="0" * 40,
        head_sha="0" * 40,
        title="Inspection",
        delivery_id="cli-inspect",
    )

    bundle = build_pull_request_bundle(client, event, settings)
    summary = inspect_bundle(bundle)
    print("=== PullRequestBundle Live Verification ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
