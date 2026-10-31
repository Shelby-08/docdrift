import json
import logging

from starlette.background import BackgroundTasks
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from docsentry.config import Settings
from docsentry.github.handler import safe_run_handler
from docsentry.github.pull_request_event import ExtractionFailure, extract_pull_request_context
from docsentry.github.signature import verify_signature
from docsentry.models import PullRequestHandler


class WebhookHandler:
    def __init__(self, settings: Settings, handler: PullRequestHandler, logger: logging.Logger):
        self.settings = settings
        self.handler = handler
        self.logger = logger
        self.router = Route("/api/github/webhooks", self.handle_webhook, methods=["POST"])

    async def handle_webhook(self, request: Request) -> JSONResponse:

        # Size check (Header)
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > 1_000_000:
                raise HTTPException(status_code=413, detail="Payload too large")

        body = await request.body()
        if len(body) > 1_000_000:
            raise HTTPException(status_code=413, detail="Payload too large")

        # Verify signature
        sig = request.headers.get("x-hub-signature-256")
        if not verify_signature(self.settings.github_webhook_secret.get_secret_value(), body, sig):
            raise HTTPException(status_code=401, detail="Invalid signature")

        # Event filter
        event = request.headers.get("x-github-event")
        delivery_id = request.headers.get("x-github-delivery")

        if event != "pull_request":
            self.logger.debug("Ignoring non-pull_request event", extra={"fields": {"event": event}})
            return JSONResponse({"status": "ignored"}, status_code=200)

        # Parse JSON
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.logger.warning(
                "Invalid JSON",
                extra={"fields": {"delivery_id": delivery_id, "reason": "invalid_json"}},
            )
            return JSONResponse({"status": "ignored"}, status_code=200)

        if not isinstance(payload, dict):
            self.logger.warning("Invalid payload", extra={"fields": {"delivery_id": delivery_id}})
            return JSONResponse({"status": "ignored"}, status_code=200)

        # Action filter
        action = payload.get("action")
        if action not in ["opened", "synchronize", "reopened"]:
            self.logger.debug("Ignoring unsupported action", extra={"fields": {"action": action}})
            return JSONResponse({"status": "ignored"}, status_code=200)

        # Validation
        result = extract_pull_request_context(payload)
        if isinstance(result, ExtractionFailure):
            self.logger.warning(
                "Malformed payload",
                extra={"fields": {"delivery_id": delivery_id, "fields": result.fields}},
            )
            return JSONResponse({"status": "ignored"}, status_code=200)

        # Background task
        bg = BackgroundTasks()
        bg.add_task(safe_run_handler, self.handler, result, delivery_id, self.logger)

        return JSONResponse({"status": "accepted"}, status_code=202, background=bg)
