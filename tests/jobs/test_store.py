from docsentry.jobs.store import BundleStore, JobRecord
from docsentry.retrieval.models import (
    PullRequestBundle,
    PullRequestContext,
    RepositoryFileIndex,
)

SHA_BASE = "a" * 40
SHA_HEAD = "b" * 40


def make_dummy_bundle() -> PullRequestBundle:
    ctx = PullRequestContext(
        delivery_id="d1",
        installation_id=10,
        owner="org",
        repository="repo",
        repository_id=1,
        pull_number=42,
        title="Test PR",
        html_url="https://github.com/org/repo/pull/42",
        base_ref="main",
        head_ref="feat",
        base_sha=SHA_BASE,
        head_sha=SHA_HEAD,
        merge_base_sha=SHA_BASE,
        state="open",
        is_draft=False,
        event_head_sha=SHA_HEAD,
        superseded_event=False,
    )
    return PullRequestBundle(
        context=ctx,
        changed_files=[],
        changed_files_complete=True,
        reported_changed_files=0,
        snapshots=[],
        skipped_files=[],
        base_index=RepositoryFileIndex(
            commit_sha=SHA_BASE, entries=[], complete=True, incomplete_reasons=[]
        ),
        head_index=RepositoryFileIndex(
            commit_sha=SHA_HEAD, entries=[], complete=True, incomplete_reasons=[]
        ),
        errors=[],
        warnings=[],
        retrieved_at="2026-11-01T00:00:00Z",
    )


def test_bundle_store_seq_and_commit() -> None:
    store = BundleStore(capacity=2)
    key = (1, 42)

    seq1 = store.next_seq(key)
    assert seq1 == 1
    assert store.latest_seq(key) == 1

    rec1 = JobRecord(
        status="succeeded",
        delivery_id="d1",
        repo_id=1,
        pr_number=42,
        event_head_sha=SHA_HEAD,
        bundle_head_sha=SHA_HEAD,
        seq=seq1,
        attempts=1,
    )
    bundle1 = make_dummy_bundle()
    assert store.commit_result(key, seq1, rec1, bundle1) is True
    assert store.get_record(key) == rec1
    assert store.get_bundle(key) == bundle1

    # Stale seq commit is rejected
    rec_old = JobRecord(
        status="failed",
        delivery_id="d0",
        repo_id=1,
        pr_number=42,
        event_head_sha=SHA_HEAD,
        bundle_head_sha=None,
        seq=0,
        attempts=1,
    )
    assert store.commit_result(key, 0, rec_old) is False
    assert store.get_record(key) == rec1


def test_bundle_store_succeeded_heads() -> None:
    store = BundleStore()
    assert store.has_succeeded_head(1, 42, SHA_HEAD) is False
    store.record_succeeded_head(1, 42, SHA_HEAD.upper())
    # Case-insensitive check
    assert store.has_succeeded_head(1, 42, SHA_HEAD.lower()) is True


def test_bundle_store_capacity_eviction() -> None:
    store = BundleStore(capacity=2)
    b1 = make_dummy_bundle()
    b2 = make_dummy_bundle()
    b3 = make_dummy_bundle()

    store.commit_result(
        (1, 1),
        1,
        JobRecord(
            status="succeeded",
            delivery_id="d1",
            repo_id=1,
            pr_number=1,
            event_head_sha=SHA_HEAD,
            bundle_head_sha=SHA_HEAD,
            seq=1,
            attempts=1,
        ),
        b1,
    )
    store.commit_result(
        (1, 2),
        1,
        JobRecord(
            status="succeeded",
            delivery_id="d2",
            repo_id=1,
            pr_number=2,
            event_head_sha=SHA_HEAD,
            bundle_head_sha=SHA_HEAD,
            seq=1,
            attempts=1,
        ),
        b2,
    )
    store.commit_result(
        (1, 3),
        1,
        JobRecord(
            status="succeeded",
            delivery_id="d3",
            repo_id=1,
            pr_number=3,
            event_head_sha=SHA_HEAD,
            bundle_head_sha=SHA_HEAD,
            seq=1,
            attempts=1,
        ),
        b3,
    )

    assert store.get_bundle((1, 1)) is None
    assert store.get_bundle((1, 2)) == b2
    assert store.get_bundle((1, 3)) == b3
