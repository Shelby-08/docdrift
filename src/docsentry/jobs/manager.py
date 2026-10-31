import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from github import Github

from docsentry.ai_review.models import AIReviewResult, AIReviewStatus
from docsentry.ai_review.service import AIReviewer, NullAIReviewer
from docsentry.config import Settings
from docsentry.github.checks import CheckHandle, CheckRunPublisher
from docsentry.intelligence.models.analysis import AnalysisResult
from docsentry.jobs.dedup import DeliveryTracker
from docsentry.jobs.store import BundleStore, JobRecord
from docsentry.models import PullRequestEventContext
from docsentry.reporting.check_run import CheckRunReport, build_report
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
        analyzer: Callable[[PullRequestBundle, Github], AnalysisResult] | None = None,
        publisher: CheckRunPublisher | None = None,
        reviewer: AIReviewer | None = None,
        head_lookup: Callable[[Github, PullRequestEventContext], str] | None = None,
    ) -> None:
        self._analyzer = analyzer
        self._publisher = publisher
        self._reviewer: AIReviewer = reviewer or NullAIReviewer()
        self._head_lookup = head_lookup
        self._results: OrderedDict[tuple[int, int], AnalysisResult] = OrderedDict()
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

    def last_result(self, key: tuple[int, int]) -> AnalysisResult | None:
        return self._results.get(key)

    async def _analyze_and_publish(
        self,
        ctx: PullRequestEventContext,
        bundle: PullRequestBundle,
        key: tuple[int, int],
        seq: int,
    ) -> tuple[str, str | None, int | None]:
        """Stage 3 + AI seam + Check Run. Never raises; returns (status, code, findings)."""
        assert self._analyzer is not None
        head_sha = bundle.context.head_sha
        client = self._auth.client_for_installation(ctx.installation_id)
        pub = self._publisher
        handle: CheckHandle | None = None
        status: str = "published"
        code: str | None = None
        if pub is not None:
            handle, begin_out = await pub.begin(
                client, ctx.owner, ctx.repo, ctx.repo_id, ctx.pr_number, head_sha
            )
            if begin_out is not None:
                status, code = begin_out.status, begin_out.code
        try:
            result = await asyncio.to_thread(self._analyzer, bundle, client)
        except Exception as exc:  # job-containment boundary
            self._logger.error("analysis_failed: %s", type(exc).__name__)
            if pub is not None and handle is not None:
                fail = CheckRunReport(
                    title="Analysis could not run safely",
                    summary="DocSentry could not complete analysis for this commit.",
                    conclusion="neutral",
                )
                await pub.finish(handle, fail, ctx.repo_id, ctx.pr_number)
            return "analysis_failed", "analysis_error", None
        self._results[key] = result
        while len(self._results) > 10:
            self._results.popitem(last=False)
        try:
            ai: AIReviewResult = await self._reviewer.review(result)
        except Exception as exc:  # AI failure never erases deterministic findings
            self._logger.warning("ai_review_failed: %s", type(exc).__name__)
            ai = AIReviewResult(status=AIReviewStatus.FAILED, error_code="ai_unexpected_error")
        count = len(result.findings)
        if pub is None or handle is None:
            return (status if pub is not None else "not_published"), code, count
        report = build_report(
            result,
            ai,
            max_annotations=self._settings.docsentry_max_annotations,
            max_summary_findings=self._settings.docsentry_max_summary_findings,
        )
        stale = self._store.latest_seq(key) > seq
        if not stale and self._head_lookup is not None:
            try:
                live = await asyncio.to_thread(self._head_lookup, client, ctx)
                stale = live.lower() != head_sha.lower()
            except Exception as exc:
                self._logger.warning("head_recheck_failed: %s", type(exc).__name__)
                await pub.cancel(handle, ctx.repo_id, ctx.pr_number)
                return "head_recheck_failed", "head_recheck_failed", count
        if stale:
            out = await pub.cancel(handle, ctx.repo_id, ctx.pr_number)
            return "superseded", out.code, count
        outcome = await pub.finish(handle, report, ctx.repo_id, ctx.pr_number)
        return outcome.status, outcome.code, count

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
            pstatus: str | None = None
            pcode: str | None = None
            fcount: int | None = None
            if self._analyzer is not None:
                pstatus, pcode, fcount = await self._analyze_and_publish(ctx, bundle, key, my_seq)
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
                publish_status=pstatus,
                publish_code=pcode,
                findings_count=fcount,
            )
            self._store.commit_result(key, my_seq, record, bundle)
            self._tracker.mark(delivery_id, "succeeded")
            return

        self._record_failure(ctx, my_seq, attempts, "max_attempts_exceeded")
