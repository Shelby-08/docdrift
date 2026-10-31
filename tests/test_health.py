import os

from fastapi.testclient import TestClient

from docsentry.app import create_app
from docsentry.config import load_settings
from docsentry.github.handler import make_default_handler
from docsentry.utils.logger import create_logger


def make_test_client() -> TestClient:
    os.environ["GITHUB_APP_ID"] = "1"
    os.environ["GITHUB_PRIVATE_KEY"] = (
        "-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----"
    )
    os.environ["GITHUB_WEBHOOK_SECRET"] = "test"

    settings = load_settings(env_file=None)
    logger = create_logger("INFO")
    handler = make_default_handler(logger)

    return TestClient(create_app(settings, handler, logger))


def test_health_endpoint():
    client = make_test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "DocSentry",
        "message": "GitHub App backend is running",
    }


def test_unknown_route_returns_404():
    client = make_test_client()

    response = client.get("/nonexistent")

    assert response.status_code == 404
    assert "error" in response.json()
