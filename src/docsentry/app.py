import logging
from collections.abc import Callable

from fastapi import FastAPI
from github import Github

from docsentry.ai_review.service import AIReviewer, NullAIReviewer, OllamaAIReviewer
from docsentry.config import Settings
from docsentry.github.checks import CheckRunPublisher
from docsentry.github.webhook import WebhookHandler
from docsentry.intelligence.models.analysis import AnalysisResult
from docsentry.intelligence.pipeline import analyze_bundle
from docsentry.jobs.dedup import DeliveryTracker
from docsentry.jobs.manager import JobManager
from docsentry.jobs.store import BundleStore
from docsentry.models import PullRequestEventContext, PullRequestHandler
from docsentry.retrieval.auth import GitHubAuthService
from docsentry.retrieval.bundle_builder import build_pull_request_bundle
from docsentry.retrieval.models import PullRequestBundle
from docsentry.retrieval.snapshots import GitHubFileReader
from docsentry.utils.errors import register_error_handlers
from docsentry.utils.logger import create_logger


def _analyze(
    settings: Settings, log: logging.Logger
) -> Callable[[PullRequestBundle, Github], AnalysisResult]:
    def run(bundle: PullRequestBundle, client: Github) -> AnalysisResult:
        c = bundle.context
        repo = client.get_repo(f"{c.owner}/{c.repository}")
        return analyze_bundle(bundle, GitHubFileReader(repo, settings, log), settings, log)

    return run


def _live_head(client: Github, ctx: PullRequestEventContext) -> str:
    return client.get_repo(f"{ctx.owner}/{ctx.repo}").get_pull(ctx.pr_number).head.sha


def create_app(
    settings: Settings,
    handler: PullRequestHandler | None = None,
    logger: logging.Logger | None = None,
) -> FastAPI:
    log = logger or create_logger(settings.log_level)
    app = FastAPI(title="DocSentry")

    active_handler: PullRequestHandler
    if handler is None:
        auth = GitHubAuthService(settings)
        store = BundleStore()
        tracker = DeliveryTracker()
        reviewer: AIReviewer = (
            OllamaAIReviewer(settings) if settings.ai_effective else NullAIReviewer()
        )
        if settings.ai_review_enabled and not settings.ai_effective:
            log.warning("ai_review_disabled: ollama_model_not_configured")
        publisher = (
            CheckRunPublisher(settings.docsentry_check_name, log)
            if settings.docsentry_publish_enabled
            else None
        )
        manager = JobManager(
            auth=auth,
            retrieve=build_pull_request_bundle,
            store=store,
            tracker=tracker,
            settings=settings,
            manager_logger=log,
            analyzer=_analyze(settings, log),
            publisher=publisher,
            reviewer=reviewer,
            head_lookup=_live_head,
        )
        active_handler = manager.submit
    else:
        active_handler = handler

    # Register Webhook Router
    webhook_handler = WebhookHandler(settings, active_handler, log)
    app.router.routes.append(webhook_handler.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "DocSentry", "message": "GitHub App backend is running"}

    register_error_handlers(app, log)
    return app
