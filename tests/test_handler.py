import asyncio
import io
import json

from docsentry.github.handler import make_default_handler, safe_run_handler
from docsentry.models import PullRequestEventContext
from docsentry.utils.logger import create_logger


def test_default_handler_logs_safe_fields():
    stream = io.StringIO()
    logger = create_logger("INFO", stream=stream)

    handler = make_default_handler(logger)
    context = PullRequestEventContext(
        action="opened",
        owner="a",
        repo="b",
        repo_id=1,
        pr_number=1,
        installation_id=1,
        base_sha="a" * 40,
        head_sha="b" * 40,
        title="Secret Title",
    )

    asyncio.run(handler(context))

    log_line = stream.getvalue().strip()
    log_data = json.loads(log_line)
    assert log_data["msg"] == "Received PR event"
    assert "Secret Title" not in log_data.get("fields", {})


def test_safe_run_handler_catches_exception():
    stream = io.StringIO()
    logger = create_logger("INFO", stream=stream)

    async def failing_handler(ctx):
        raise ValueError("Test Error")

    asyncio.run(safe_run_handler(failing_handler, None, "delivery-123", logger))

    log_line = stream.getvalue().strip()
    log_data = json.loads(log_line)
    assert log_data["level"] == "ERROR"
    assert log_data["msg"] == "PR event handler failed"
