import logging

from fastapi import FastAPI

from docsentry.config import Settings
from docsentry.github.webhook import WebhookHandler
from docsentry.jobs.dedup import DeliveryTracker
from docsentry.jobs.manager import JobManager
from docsentry.jobs.store import BundleStore
from docsentry.models import PullRequestHandler
from docsentry.retrieval.auth import GitHubAuthService
from docsentry.retrieval.bundle_builder import build_pull_request_bundle
from docsentry.utils.errors import register_error_handlers
from docsentry.utils.logger import create_logger


def create_app(
    settings: Settings,
    handler: PullRequestHandler | None = None,
    logger: logging.Logger | None = None,
) -> FastAPI:
    log = logger or create_logger(settings.log_level)
    app = FastAPI(title="DocSentry")

    if handler is None:
        auth = GitHubAuthService(settings)
        store = BundleStore()
        tracker = DeliveryTracker()
        manager = JobManager(
            auth=auth,
            retrieve=build_pull_request_bundle,
            store=store,
            tracker=tracker,
            settings=settings,
            manager_logger=log,
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
