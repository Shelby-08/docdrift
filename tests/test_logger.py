import io
import json

from docsentry.utils.logger import create_logger


def test_redacts_sensitive_keys() -> None:
    stream = io.StringIO()
    logger = create_logger("INFO", stream=stream)

    # Log a message with extra fields
    logger.info("Test message", extra={"fields": {"api_key": "12345", "msg": "normal"}})

    log_data = json.loads(stream.getvalue().strip())

    assert log_data["msg"] == "Test message"
    # The 'fields' key should be preserved but 'api_key' redacted
    assert "fields" in log_data
    assert log_data["fields"]["api_key"] == "[REDACTED]"
    assert log_data["fields"]["msg"] == "normal"


def test_creating_logger_twice_does_not_duplicate_lines() -> None:
    create_logger("INFO", stream=io.StringIO())
    stream = io.StringIO()
    logger = create_logger("INFO", stream=stream)
    logger.info("once")
    assert len(stream.getvalue().strip().splitlines()) == 1
