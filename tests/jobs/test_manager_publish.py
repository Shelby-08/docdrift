import asyncio
from typing import Any

from github import GithubException

from docsentry.ai_review.models import AIReviewResult, AIReviewStatus
from docsentry.github.checks import CheckRunPublisher
from docsentry.intelligence.models.analysis import AnalysisResult
from docsentry.jobs.dedup import DeliveryTracker
from docsentry.jobs.manager import JobManager
from docsentry.jobs.store import BundleStore
from tests.intelligence.test_pipeline import BASE, HEAD, run
from tests.jobs.test_manager import FakeAuth, make_ctx, make_dummy_bundle, make_settings
from tests.test_checks_adapter import FakeClient, FakeRepo

KEY = (100, 42)


class Auth(FakeAuth):
    def __init__(self, repo: FakeRepo) -> None:
        self.client = FakeClient(repo)

    def client_for_installation(self, installation_id: int) -> Any:
        return self.client


class Env:
    def __init__(self, **kw: Any) -> None:
        self.repo = FakeRepo(create_exc=kw.pop("create_exc", None))
        self.store, self.tracker = BundleStore(), DeliveryTracker()
        self.calls = 0
        analyzer = kw.pop("analyzer", None)
        self.result = run(BASE, HEAD)

        def default(bundle: Any, client: Any) -> AnalysisResult:
            self.calls += 1
            if analyzer:
                return analyzer(self)  # type: ignore[no-any-return]
            return self.result

        self.mgr = JobManager(
            Auth(self.repo),  # type: ignore[arg-type]
            lambda *a, **k: make_dummy_bundle(),
            self.store,
            self.tracker,
            make_settings(),
            analyzer=default,
            publisher=CheckRunPublisher("DocSentry"),
            **kw,
        )

    def submit(self, delivery: str = "d1") -> None:
        asyncio.run(self.mgr.submit(make_ctx(delivery)))

    @property
    def run_calls(self) -> list[dict[str, Any]]:
        return self.repo.existing[0].calls if self.repo.existing else []


def test_end_to_end_publish_with_ai_disabled() -> None:
    e = Env()
    e.submit()
    rec = e.store.get_record(KEY)
    assert rec and rec.status == "succeeded" and rec.publish_status == "published"
    assert rec.findings_count == 1
    done = e.run_calls[-1]
    assert done["status"] == "completed" and done["conclusion"] == "neutral"
    assert done["output"]["annotations"][0]["path"] == "docs/configuration.md"
    assert "skipped_disabled" in done["output"]["summary"]
    assert e.mgr.last_result(KEY) is e.result


def test_duplicate_delivery_one_run_one_analysis() -> None:
    e = Env()
    e.submit("d1")
    e.submit("d1")
    assert e.calls == 1 and len(e.repo.created) == 1


def test_redelivery_same_head_does_not_create_second_run() -> None:
    e = Env()
    e.submit("d1")
    e.submit("d2")
    assert e.calls == 1 and len(e.repo.created) == 1


def test_publish_failure_keeps_analysis() -> None:
    e = Env(create_exc=GithubException(403, {}, {}))
    e.submit()
    rec = e.store.get_record(KEY)
    assert rec and rec.status == "succeeded" and rec.publish_status == "failed"
    assert rec.publish_code == "github_checks_permission_missing"
    assert e.mgr.last_result(KEY) is not None and rec.findings_count == 1


def test_fork_unavailable_is_not_reported_published() -> None:
    e = Env(create_exc=GithubException(422, {}, {}))
    e.submit()
    rec = e.store.get_record(KEY)
    assert rec and rec.publish_status == "unavailable"
    assert rec.publish_code == "github_check_unavailable_for_head"


def test_analysis_crash_completes_run_neutral() -> None:
    def boom(env: Env) -> AnalysisResult:
        raise RuntimeError("secret detail")

    e = Env(analyzer=boom)
    e.submit()
    rec = e.store.get_record(KEY)
    assert rec and rec.publish_status == "analysis_failed" and rec.publish_code == "analysis_error"
    assert e.run_calls[-1]["conclusion"] == "neutral"
    assert "secret detail" not in str(e.run_calls)


def test_stale_via_newer_job_cancels_own_run_only() -> None:
    def newer(env: Env) -> AnalysisResult:
        env.store.next_seq(KEY)  # a newer delivery for the same PR arrived mid-analysis
        return env.result

    e = Env(analyzer=newer)
    e.submit()
    rec = e.store.get_record(KEY)
    assert rec is not None and rec.publish_status == "superseded"
    assert e.run_calls[-1]["conclusion"] == "cancelled"
    assert not any(c.get("conclusion") == "neutral" for c in e.run_calls)


def test_live_head_recheck_detects_stale_snapshot() -> None:
    e = Env(head_lookup=lambda client, ctx: "c" * 40)
    e.submit()
    rec = e.store.get_record(KEY)
    assert rec and rec.publish_status == "superseded"
    assert e.run_calls[-1]["conclusion"] == "cancelled"


def test_head_recheck_failure_never_assumes_currency() -> None:
    def fail(client: Any, ctx: Any) -> str:
        raise OSError("net")

    e = Env(head_lookup=fail)
    e.submit()
    rec = e.store.get_record(KEY)
    assert rec and rec.publish_status == "head_recheck_failed"
    assert e.run_calls[-1]["conclusion"] == "cancelled"


def test_ai_exception_still_publishes_deterministic_result() -> None:
    class Bad:
        async def review(self, result: AnalysisResult) -> AIReviewResult:
            raise ValueError("model exploded")

    e = Env(reviewer=Bad())
    e.submit()
    rec = e.store.get_record(KEY)
    assert rec and rec.publish_status == "published"
    assert "Status: `failed`" in e.run_calls[-1]["output"]["summary"]


def test_ai_unavailable_status_shown_and_findings_kept() -> None:
    class Down:
        async def review(self, result: AnalysisResult) -> AIReviewResult:
            return AIReviewResult(
                status=AIReviewStatus.UNAVAILABLE, error_code="ollama_unreachable"
            )

    e = Env(reviewer=Down())
    e.submit()
    summary = e.run_calls[-1]["output"]["summary"]
    assert "ollama" in summary and "docs/configuration.md" in summary


def test_no_publisher_keeps_stage2_behaviour() -> None:
    store = BundleStore()
    mgr = JobManager(
        FakeAuth(), lambda *a, **k: make_dummy_bundle(), store, DeliveryTracker(), make_settings()
    )  # type: ignore[arg-type]
    asyncio.run(mgr.submit(make_ctx()))
    rec = store.get_record(KEY)
    assert rec and rec.status == "succeeded" and rec.publish_status is None
