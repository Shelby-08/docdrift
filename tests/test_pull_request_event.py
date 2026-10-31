import json
from pathlib import Path

from docsentry.github.pull_request_event import ExtractionFailure, extract_pull_request_context

FIXTURES = Path(__file__).parent / "fixtures"


def test_valid_opened():
    with open(FIXTURES / "pull_request_opened.json") as f:
        payload = json.load(f)
    result = extract_pull_request_context(payload)
    assert not isinstance(result, ExtractionFailure)
    assert result.action == "opened"
    assert result.pr_number == 123


def test_valid_synchronize():
    with open(FIXTURES / "pull_request_synchronize.json") as f:
        payload = json.load(f)
    result = extract_pull_request_context(payload)
    assert not isinstance(result, ExtractionFailure)
    assert result.action == "synchronize"


def test_valid_reopened():
    with open(FIXTURES / "pull_request_reopened.json") as f:
        payload = json.load(f)
    result = extract_pull_request_context(payload)
    assert not isinstance(result, ExtractionFailure)
    assert result.action == "reopened"


def test_missing_field():
    result = extract_pull_request_context({"action": "opened"})
    assert isinstance(result, ExtractionFailure)
    assert "repository.name" in result.fields


def test_bad_sha():
    payload = {
        "action": "opened",
        "repository": {"id": 1, "name": "test", "owner": {"login": "test"}},
        "pull_request": {
            "number": 1,
            "title": "test",
            "base": {"sha": "bad"},
            "head": {"sha": "bad"},
        },
        "installation": {"id": 1},
    }
    result = extract_pull_request_context(payload)
    assert isinstance(result, ExtractionFailure)
    assert "pull_request.base.sha" in result.fields


def test_bad_action():
    payload = {
        "action": "closed",
        "repository": {"id": 1, "name": "test", "owner": {"login": "test"}},
        "pull_request": {
            "number": 1,
            "title": "test",
            "base": {"sha": "a" * 40},
            "head": {"sha": "b" * 40},
        },
        "installation": {"id": 1},
    }
    result = extract_pull_request_context(payload)
    assert isinstance(result, ExtractionFailure)
    assert "action" in result.fields
