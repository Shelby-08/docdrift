from typing import Any

import pytest

from docsentry.config import Settings
from docsentry.jobs.dedup import DeliveryTracker
from docsentry.jobs.manager import JobManager
from docsentry.jobs.store import BundleStore
from docsentry.models import PullRequestEventContext
from docsentry.retrieval.errors import AuthenticationFailure, TransientFailure
from docsentry.retrieval.models import (
    PullRequestBundle,
    PullRequestContext,
    RepositoryFileIndex,
)

SHA_BASE = "a" * 40
SHA_HEAD = "b" * 40


def make_settings(max_job_attempts: int = 3) -> Settings:
    return Settings(
        github_app_id="123",
        github_private_key="key",
        github_webhook_secret="sec",
        max_job_attempts=max_job_attempts,
    )


class FakeAuth:
    def client_for_installation(self, installation_id: int) -> Any:
        return object()


def make_ctx(
    delivery_id: str = "d1",
    pr_number: int = 42,
    head_sha: str = SHA_HEAD,
) -> PullRequestEventContext:
    return PullRequestEventContext(
        action="opened",
        owner="org",
        repo="repo",
        repo_id=100,
        installation_id=10,
        pr_number=pr_number,
        base_sha=SHA_BASE,
        head_sha=head_sha,
        title="PR title",
        delivery_id=delivery_id,
    )


def make_dummy_bundle(head_sha: str = SHA_HEAD) -> PullRequestBundle:
    ctx = PullRequestContext(
        repo_id=100,
        repo_full_name="org/repo",
        pr_number=42,
        base_ref="main",
        base_sha=SHA_BASE,
        head_ref="feat",
        head_sha=head_sha,
        head_repo_full_name="org/repo",
        head_repo_fork=False,
        is_cross_repository=False,
        merge_base_sha=SHA_BASE,
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
            commit_sha=head_sha, entries=[], complete=True, incomplete_reasons=[]
        ),
        errors=[],
        warnings=[],
        retrieved_at="2026-11-01T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_job_manager_success() -> None:
    store = BundleStore()
    tracker = DeliveryTracker()
    settings = make_settings()
    bundle = make_dummy_bundle()

    def fake_retrieve(*args: Any, **kwargs: Any) -> PullRequestBundle:
        return bundle

    mgr = JobManager(FakeAuth(), fake_retrieve, store, tracker, settings)  # type: ignore[arg-type]
    ctx = make_ctx()

    await mgr.submit(ctx)

    rec = store.get_record((100, 42))
    assert rec is not None
    assert rec.status == "succeeded"
    assert rec.delivery_id == "d1"
    assert store.get_bundle((100, 42)) == bundle
    assert tracker.get_state("d1") == "succeeded"


@pytest.mark.asyncio
async def test_job_manager_duplicate_delivery() -> None:
    store = BundleStore()
    tracker = DeliveryTracker()
    settings = make_settings()
    retrieve_calls = 0

    def fake_retrieve(*args: Any, **kwargs: Any) -> PullRequestBundle:
        nonlocal retrieve_calls
        retrieve_calls += 1
        return make_dummy_bundle()

    mgr = JobManager(FakeAuth(), fake_retrieve, store, tracker, settings)  # type: ignore[arg-type]
    ctx = make_ctx("d_same")

    await mgr.submit(ctx)
    await mgr.submit(ctx)

    assert retrieve_calls == 1


@pytest.mark.asyncio
async def test_job_manager_duplicate_head_sha() -> None:
    store = BundleStore()
    tracker = DeliveryTracker()
    settings = make_settings()
    mgr = JobManager(FakeAuth(), lambda *args, **kw: make_dummy_bundle(), store, tracker, settings)  # type: ignore[arg-type]

    await mgr.submit(make_ctx("d1", head_sha=SHA_HEAD))
    rec1 = store.get_record((100, 42))
    assert rec1 is not None and rec1.status == "succeeded"

    await mgr.submit(make_ctx("d2", head_sha=SHA_HEAD))
    rec2 = store.get_record((100, 42))
    assert rec2 is not None and rec2.status == "duplicate"


@pytest.mark.asyncio
async def test_job_manager_retries_transient_failure() -> None:
    store = BundleStore()
    tracker = DeliveryTracker()
    settings = make_settings(max_job_attempts=2)
    attempts = 0
    sleeps: list[float] = []

    async def fake_sleep(dur: float) -> None:
        sleeps.append(dur)

    def fake_retrieve(*args: Any, **kwargs: Any) -> PullRequestBundle:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TransientFailure(operation="read", message="timeout")
        return make_dummy_bundle()

    mgr = JobManager(
        FakeAuth(),  # type: ignore[arg-type]
        fake_retrieve,
        store,
        tracker,
        settings,
        sleep=fake_sleep,
    )
    await mgr.submit(make_ctx())

    rec = store.get_record((100, 42))
    assert rec is not None and rec.status == "succeeded"
    assert attempts == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_job_manager_non_retryable_failure() -> None:
    store = BundleStore()
    tracker = DeliveryTracker()
    settings = make_settings(max_job_attempts=3)
    attempts = 0

    def fake_retrieve(*args: Any, **kwargs: Any) -> PullRequestBundle:
        nonlocal attempts
        attempts += 1
        raise AuthenticationFailure(message="bad key")

    mgr = JobManager(FakeAuth(), fake_retrieve, store, tracker, settings)  # type: ignore[arg-type]
    await mgr.submit(make_ctx())

    rec = store.get_record((100, 42))
    assert rec is not None
    assert rec.status == "failed"
    assert rec.error_code == "auth_failed"
    assert attempts == 1
    assert tracker.get_state("d1") == "failed"
