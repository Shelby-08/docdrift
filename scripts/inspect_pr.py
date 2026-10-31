#!/usr/bin/env python3
"""Offline and live verification script for the Stage 2 PullRequestBundle.

Usage:
    python scripts/inspect_pr.py --offline
    python scripts/inspect_pr.py --owner OWNER --repo NAME --pr 1 --installation-id 123

The live path performs GET requests only and prints counts, never file contents.
"""

import argparse
import hashlib
import json
import sys
from typing import Any

from docsentry.config import load_settings
from docsentry.models import PullRequestEventContext
from docsentry.retrieval.auth import GitHubAuthService
from docsentry.retrieval.bundle_builder import build_pull_request_bundle
from docsentry.retrieval.classify import classify_path
from docsentry.retrieval.models import (
    ChangedFile,
    FileSnapshot,
    FileVersion,
    PullRequestBundle,
    PullRequestContext,
    RepositoryFileEntry,
    RepositoryFileIndex,
)


def _blob(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def make_offline_bundle() -> PullRequestBundle:
    base_sha, head_sha, orig_base = "a" * 40, "b" * 40, "c" * 40
    files = {
        "docs/arch.md": ("# Arch\n\nOld documentation.\n", "# Arch\n\nNew documentation.\n"),
        "src/core.py": ("def run():\n    pass\n", "def run():\n    return True\n"),
    }
    ctx = PullRequestContext(
        delivery_id="cli-inspect",
        installation_id=1,
        owner="test-org",
        repository="test-repo",
        repository_id=101,
        pull_number=1,
        title="offline",
        html_url="https://example.invalid/pull/1",
        base_ref="main",
        head_ref="feature",
        base_sha=orig_base,
        head_sha=head_sha,
        merge_base_sha=base_sha,
        state="open",
        is_draft=False,
        event_head_sha=head_sha,
    )
    changed: list[ChangedFile] = []
    snapshots: list[FileSnapshot] = []
    base_entries: list[RepositoryFileEntry] = []
    head_entries: list[RepositoryFileEntry] = []
    for path, (old, new) in files.items():
        category = classify_path(path)
        changed.append(
            ChangedFile(
                filename=path,
                status="modified",
                additions=1,
                deletions=1,
                changes=2,
                blob_sha=_blob(new),
                category=category,
            )
        )
        snapshots.append(
            FileSnapshot(
                path=path,
                status="modified",
                before=FileVersion(
                    path=path, commit_sha=base_sha, blob_sha=_blob(old), size=len(old), text=old
                ),
                after=FileVersion(
                    path=path, commit_sha=head_sha, blob_sha=_blob(new), size=len(new), text=new
                ),
            )
        )
        for entries, sha, text in ((base_entries, base_sha, old), (head_entries, head_sha, new)):
            entries.append(
                RepositoryFileEntry(
                    path=path,
                    type="blob",
                    mode="100644",
                    blob_sha=_blob(text),
                    size=len(text),
                    commit_sha=sha,
                    category=category,
                )
            )
    return PullRequestBundle(
        context=ctx,
        changed_files=changed,
        changed_files_complete=True,
        reported_changed_files=len(changed),
        snapshots=snapshots,
        skipped_files=[],
        base_index=RepositoryFileIndex(commit_sha=base_sha, entries=base_entries, complete=True),
        head_index=RepositoryFileIndex(commit_sha=head_sha, entries=head_entries, complete=True),
        errors=[],
        warnings=[],
        retrieved_at="2026-11-01T00:00:00Z",
    )


def inspect_bundle(bundle: PullRequestBundle) -> dict[str, Any]:
    return {
        "pull_number": bundle.context.pull_number,
        "repository": f"{bundle.context.owner}/{bundle.context.repository}",
        "base_sha": bundle.context.base_sha,
        "head_sha": bundle.context.head_sha,
        "merge_base_sha": bundle.context.merge_base_sha,
        "changed_files_count": len(bundle.changed_files),
        "snapshots_count": len(bundle.snapshots),
        "skipped_files_count": len(bundle.skipped_files),
        "base_index_entries": len(bundle.base_index.entries),
        "head_index_entries": len(bundle.head_index.entries),
        "error_codes": [e.code for e in bundle.errors],
        "warnings_count": len(bundle.warnings),
        "complete": bundle.is_complete(),
        "retrieved_at": bundle.retrieved_at,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a PullRequestBundle")
    parser.add_argument("--offline", action="store_true", help="Run an offline synthetic check")
    parser.add_argument("--owner", type=str)
    parser.add_argument("--repo", type=str)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--installation-id", type=int, default=1)
    args = parser.parse_args()

    if args.offline or not (args.owner and args.repo and args.pr):
        print("=== PullRequestBundle Offline Verification ===")
        print(json.dumps(inspect_bundle(make_offline_bundle()), indent=2))
        sys.exit(0)

    settings = load_settings()
    client = GitHubAuthService(settings).client_for_installation(args.installation_id)
    event = PullRequestEventContext(
        action="synchronize",
        owner=args.owner,
        repo=args.repo,
        repo_id=0,
        pr_number=args.pr,
        installation_id=args.installation_id,
        base_sha="0" * 40,
        head_sha="0" * 40,
        title="",
        delivery_id="cli-inspect",
    )
    bundle = build_pull_request_bundle(client, event, settings)
    print("=== PullRequestBundle Live Verification ===")
    print(json.dumps(inspect_bundle(bundle), indent=2))


if __name__ == "__main__":
    main()
