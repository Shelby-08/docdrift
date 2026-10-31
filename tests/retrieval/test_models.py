import pytest
from pydantic import ValidationError

from docsentry.retrieval.models import (
    ChangedFile,
    PullRequestBundle,
    PullRequestContext,
    RepositoryFileEntry,
    RepositoryFileIndex,
    RetrievalError,
)

SHA_A = "a" * 40
SHA_B = "b" * 40


def test_pull_request_context_valid() -> None:
    ctx = PullRequestContext(
        delivery_id="deliv-1",
        installation_id=100,
        owner="octocat",
        repository="hello-world",
        repository_id=200,
        pull_number=12,
        title="Fix bug",
        html_url="https://github.com/octocat/hello-world/pull/12",
        base_ref="main",
        head_ref="patch-1",
        base_sha=SHA_A,
        head_sha=SHA_B,
        merge_base_sha=SHA_A,
        state="open",
        is_draft=False,
        event_head_sha=SHA_B,
        superseded_event=False,
    )
    assert ctx.owner == "octocat"
    assert ctx.base_sha == SHA_A


def test_pull_request_context_invalid_sha() -> None:
    with pytest.raises(ValidationError):
        PullRequestContext(
            delivery_id="deliv-1",
            installation_id=100,
            owner="octocat",
            repository="hello-world",
            repository_id=200,
            pull_number=12,
            title="Fix bug",
            html_url="https://github.com/octocat/hello-world/pull/12",
            base_ref="main",
            head_ref="patch-1",
            base_sha="invalid-sha",
            head_sha=SHA_B,
            state="open",
            is_draft=False,
            event_head_sha=SHA_B,
        )


def test_bundle_unchanged_doc_paths_and_completeness() -> None:
    ctx = PullRequestContext(
        delivery_id="deliv-1",
        installation_id=100,
        owner="octocat",
        repository="hello-world",
        repository_id=200,
        pull_number=12,
        title="Fix bug",
        html_url="https://github.com/octocat/hello-world/pull/12",
        base_ref="main",
        head_ref="patch-1",
        base_sha=SHA_A,
        head_sha=SHA_B,
        merge_base_sha=SHA_A,
        state="open",
        is_draft=False,
        event_head_sha=SHA_B,
        superseded_event=False,
    )

    changed = [
        ChangedFile(
            filename="docs/changed.md",
            previous_filename=None,
            status="modified",
            additions=5,
            deletions=2,
            changes=7,
            blob_sha=SHA_A,
            category="doc",
        ),
        ChangedFile(
            filename="docs/renamed_to.md",
            previous_filename="docs/renamed_from.md",
            status="renamed",
            additions=0,
            deletions=0,
            changes=0,
            blob_sha=SHA_A,
            category="doc",
        ),
    ]

    head_entries = [
        RepositoryFileEntry(
            path="docs/changed.md",
            type="blob",
            mode="100644",
            blob_sha=SHA_A,
            commit_sha=SHA_B,
            category="doc",
        ),
        RepositoryFileEntry(
            path="docs/unchanged.md",
            type="blob",
            mode="100644",
            blob_sha=SHA_A,
            commit_sha=SHA_B,
            category="doc",
        ),
        RepositoryFileEntry(
            path="docs/renamed_to.md",
            type="blob",
            mode="100644",
            blob_sha=SHA_A,
            commit_sha=SHA_B,
            category="doc",
        ),
        RepositoryFileEntry(
            path="src/code.py",
            type="blob",
            mode="100644",
            blob_sha=SHA_A,
            commit_sha=SHA_B,
            category="source",
        ),
    ]

    base_index = RepositoryFileIndex(commit_sha=SHA_A, entries=[], complete=True)
    head_index = RepositoryFileIndex(commit_sha=SHA_B, entries=head_entries, complete=True)

    bundle = PullRequestBundle(
        context=ctx,
        changed_files=changed,
        changed_files_complete=True,
        reported_changed_files=2,
        snapshots=[],
        skipped_files=[],
        base_index=base_index,
        head_index=head_index,
        errors=[],
        warnings=[],
        retrieved_at="2026-11-01T00:00:00Z",
    )

    assert bundle.unchanged_doc_paths() == ["docs/unchanged.md"]
    assert bundle.is_complete() is True

    # Incomplete if fatal error exists
    bundle_with_error = bundle.model_copy(
        update={"errors": [RetrievalError(code="fatal_fetch", operation="fetch", message="failed")]}
    )
    assert bundle_with_error.is_complete() is False

    # Incomplete if changed_files_complete is False
    bundle_incomplete_files = bundle.model_copy(update={"changed_files_complete": False})
    assert bundle_incomplete_files.is_complete() is False

    # Still complete if error is a warning
    bundle_with_warning = bundle.model_copy(
        update={"errors": [RetrievalError(code="warning", operation="fetch", message="fallback")]}
    )
    assert bundle_with_warning.is_complete() is True
