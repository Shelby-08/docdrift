import logging
from collections.abc import Awaitable, Callable
from typing import Any

from docsentry.models import PullRequestEventContext, PullRequestHandler


def make_default_handler(logger: logging.Logger) -> PullRequestHandler:
    async def handler(context: PullRequestEventContext) -> None:
        logger.info(
            "Received PR event",
            extra={
                "fields": {
                    "action": context.action,
                    "owner": context.owner,
                    "repo": context.repo,
                    "repo_id": context.repo_id,
                    "pr_number": context.pr_number,
                    "installation_id": context.installation_id,
                    "base_sha": context.base_sha,
                    "head_sha": context.head_sha,
                }
            },
        )

    return handler


async def safe_run_handler(
    handler: Callable[[Any], Awaitable[None]],
    context: PullRequestEventContext | None,
    delivery_id: str | None,
    logger: logging.Logger,
) -> None:
    try:
        await handler(context)
    except Exception as exc:
        logger.error(
            "PR event handler failed",
            extra={
                "fields": {
                    "delivery_id": delivery_id,
                    "error_type": type(exc).__name__,
                }
            },
        )
