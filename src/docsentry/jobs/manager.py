import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from docsentry.config import Settings
from docsentry.jobs.dedup import DeliveryTracker
from docsentry.jobs.store import BundleStore, JobRecord
from docsentry.models import PullRequestEventContext
from docsentry.retrieval.auth import GitHubAuthService
from docsentry.retrieval.errors import (
    AuthenticationFailure,
    GitHubRetrievalFailure,
    InstallationUnavailable,
    InvalidRequest,
    JobSuperseded,
    PermissionDenied,
    RateLimited,
    ResourceNotFound,
)
from docsentry.retrieval.models import PullRequestBundle

logger = logging.getLogger(__name__)


class JobManager:
    """Coordinates background PR retrieval jobs, concurrency, dedup and retries."""

    def __init__(
        self,
        auth: GitHubAuthService,
        retrieve: Callable[..., PullRequestBundle],
        store: BundleStore,
        tracker: DeliveryTracker,
        settings: Settings,
        manager_logger: logging.Logger | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._auth = auth
        self._retrieve = retrieve
        self._store = store
        self._tracker = tracker
        self._settings = settings
        self._logger = manager_logger or logger
        self._sleep = sleep
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)

    def _record_superseded(self, ctx: PullRequestEventContext, seq: int, attempts: int) -> None:
        key = (ctx.repo_id, ctx.pr_number)
        record = JobRecord(
            status="superseded",
            delivery_id=ctx.delivery_id,
            repo_id=ctx.repo_id,
            pr_number=ctx.pr_number,
            event_head_sha=ctx.head_sha,
            bundle_head_sha=None,
            seq=seq,
            attempts=attempts,
            finished_at=datetime.now(UTC).isoformat(),
        )
        self._store.commit_result(key, seq, record)
        self._tracker.mark(ctx.delivery_id, "superseded")
        self._logger.info(
            "Job superseded: repo_id=%d pr_number=%d seq=%d",
            ctx.repo_id,
            ctx.pr_number,
            seq,
        )

    def _record_failure(
        self, ctx: PullRequestEventContext, seq: int, attempts: int, code: str
    ) -> None:
        key = (ctx.repo_id, ctx.pr_number)
        record = JobRecord(
            status="failed",
            delivery_id=ctx.delivery_id,
            repo_id=ctx.repo_id,
            pr_number=ctx.pr_number,
            event_head_sha=ctx.head_sha,
            bundle_head_sha=None,
            seq=seq,
            attempts=attempts,
            error_code=code,
            finished_at=datetime.now(UTC).isoformat(),
        )
        self._store.commit_result(key, seq, record)
        self._tracker.mark(ctx.delivery_id, "failed")
        self._logger.warning(
            "Job failed: repo_id=%d pr_number=%d code=%s attempts=%d",
            ctx.repo_id,
            ctx.pr_number,
            code,
            attempts,
        )

    async def _run_attempt(
        self,
        ctx: PullRequestEventContext,
        key: tuple[int, int],
        my_seq: int,
    ) -> PullRequestBundle:
        async with self._semaphore:
            if self._store.latest_seq(key) > my_seq:
                raise JobSuperseded()

            client = self._auth.client_for_installation(ctx.installation_id)

            def should_abort() -> bool:
                return self._store.latest_seq(key) > my_seq

            bundle = await asyncio.to_thread(
                self._retrieve,
                client,
                ctx,
                self._settings,
                self._logger,
                should_abort,
            )
            return bundle

    async def submit(self, ctx: PullRequestEventContext) -> None:
        """Execute PR retrieval in background; safe entry point for webhook handler."""
        delivery_id = ctx.delivery_id
        if not self._tracker.begin(delivery_id):
            self._logger.info("duplicate_delivery: %s", delivery_id)
            return

        key = (ctx.repo_id, ctx.pr_number)
        my_seq = self._store.next_seq(key)
        attempts = 0

        while attempts < self._settings.max_job_attempts:
            attempts += 1
            if self._store.latest_seq(key) > my_seq:
                self._record_superseded(ctx, my_seq, attempts)
                return

            try:
                bundle = await self._run_attempt(ctx, key, my_seq)
            except JobSuperseded:
                self._record_superseded(ctx, my_seq, attempts)
                return
            except RateLimited as exc:
                if exc.retry_after_seconds and exc.retry_after_seconds > 30:
                    self._record_failure(ctx, my_seq, attempts, "rate_limited")
                    return
                if attempts < self._settings.max_job_attempts:
                    backoff = float(2 ** (attempts - 1))
                    await self._sleep(backoff)
                    continue
                self._record_failure(ctx, my_seq, attempts, "rate_limited")
                return
            except (
                AuthenticationFailure,
                InstallationUnavailable,
                PermissionDenied,
                ResourceNotFound,
                InvalidRequest,
            ) as exc:
                self._record_failure(ctx, my_seq, attempts, exc.code)
                return
            except GitHubRetrievalFailure as exc:
                if not exc.retryable:
                    self._record_failure(ctx, my_seq, attempts, exc.code)
                    return
                if attempts < self._settings.max_job_attempts:
                    backoff = float(2 ** (attempts - 1))
                    await self._sleep(backoff)
                    continue
                self._record_failure(ctx, my_seq, attempts, exc.code)
                return
            except Exception as exc:
                self._logger.error("Unexpected error in job: %s", type(exc).__name__)
                self._record_failure(ctx, my_seq, attempts, "unexpected_error")
                return

            # Successfully retrieved bundle
            head_sha = bundle.context.head_sha
            if self._store.has_succeeded_head(ctx.repo_id, ctx.pr_number, head_sha):
                record = JobRecord(
                    status="duplicate",
                    delivery_id=delivery_id,
                    repo_id=ctx.repo_id,
                    pr_number=ctx.pr_number,
                    event_head_sha=ctx.head_sha,
                    bundle_head_sha=head_sha,
                    seq=my_seq,
                    attempts=attempts,
                    finished_at=datetime.now(UTC).isoformat(),
                )
                self._store.commit_result(key, my_seq, record)
                self._tracker.mark(delivery_id, "succeeded")
                return

            self._store.record_succeeded_head(ctx.repo_id, ctx.pr_number, head_sha)
            record = JobRecord(
                status="succeeded",
                delivery_id=delivery_id,
                repo_id=ctx.repo_id,
                pr_number=ctx.pr_number,
                event_head_sha=ctx.head_sha,
                bundle_head_sha=head_sha,
                seq=my_seq,
                attempts=attempts,
                finished_at=datetime.now(UTC).isoformat(),
            )
            self._store.commit_result(key, my_seq, record, bundle)
            self._tracker.mark(delivery_id, "succeeded")
            return

        self._record_failure(ctx, my_seq, attempts, "max_attempts_exceeded")
