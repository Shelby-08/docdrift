import logging

from fastapi import FastAPI

from docsentry.config import Settings
from docsentry.github.webhook import WebhookHandler
from docsentry.models import PullRequestHandler
from docsentry.utils.errors import register_error_handlers


def create_app(settings: Settings, handler: PullRequestHandler, logger: logging.Logger) -> FastAPI:
    app = FastAPI(title="DocSentry")

    # Register Webhook Router
    webhook_handler = WebhookHandler(settings, handler, logger)
    app.router.routes.append(webhook_handler.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "DocSentry", "message": "GitHub App backend is running"}

    register_error_handlers(app, logger)
    return app
