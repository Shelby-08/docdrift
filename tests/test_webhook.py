import hashlib
import hmac
import json
import os
from io import StringIO
from uuid import uuid4

from fastapi.testclient import TestClient

from docsentry.app import create_app
from docsentry.config import load_settings
from docsentry.github.handler import make_default_handler
from docsentry.utils.logger import create_logger

SECRET = "test_secret"
os.environ["GITHUB_APP_ID"] = "1"
os.environ["GITHUB_PRIVATE_KEY"] = (
    "-----BEGIN RSA PRIVATE KEY-----\nFAKE\n-----END RSA PRIVATE KEY-----"
)
os.environ["GITHUB_WEBHOOK_SECRET"] = SECRET

settings = load_settings(env_file=None)
stream = StringIO()
logger = create_logger("INFO", stream=stream)
handler = make_default_handler(logger)
client = TestClient(create_app(settings, handler, logger))


def sign_request(body_dict):
    body_bytes = json.dumps(body_dict).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
    return body_bytes, sig


def build_payload(action):
    return {
        "action": action,
        "repository": {"id": 1, "name": "test", "owner": {"login": "test"}},
        "pull_request": {
            "number": 1,
            "title": "test",
            "base": {"sha": "a" * 40},
            "head": {"sha": "b" * 40},
        },
        "installation": {"id": 1},
    }


def test_valid_opened():
    body, sig = sign_request(build_payload("opened"))
    resp = client.post(
        "/api/github/webhooks",
        data=body,
        headers={
            "content-type": "application/json",
            "x-github-event": "pull_request",
            "x-github-delivery": str(uuid4()),
            "x-hub-signature-256": sig,
        },
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


def test_missing_signature():
    resp = client.post("/api/github/webhooks", json=build_payload("opened"))
    assert resp.status_code == 401


def test_tampered_body():
    body, sig = sign_request(build_payload("opened"))
    body = body + b"tampered"
    resp = client.post(
        "/api/github/webhooks",
        data=body,
        headers={
            "content-type": "application/json",
            "x-github-event": "pull_request",
            "x-github-delivery": str(uuid4()),
            "x-hub-signature-256": sig,
        },
    )
    assert resp.status_code == 401


def test_wrong_action():
    body, sig = sign_request(build_payload("closed"))
    resp = client.post(
        "/api/github/webhooks",
        data=body,
        headers={
            "content-type": "application/json",
            "x-github-event": "pull_request",
            "x-github-delivery": str(uuid4()),
            "x-hub-signature-256": sig,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_invalid_json():
    # We must sign a valid JSON string but then replace the body to be invalid
    # But the signature would be wrong. The prompt implies valid signature, bad JSON.
    # To test "signed but malformed", we need to construct a request that passes signature check.
    # The only way is if we sign the *bad* body? No, the prompt says "signed but malformed".
    # This usually means the signature matches the body, but the body is not valid JSON.
    # So we sign the invalid body.

    body = b"not json"
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    resp = client.post(
        "/api/github/webhooks",
        data=body,
        headers={
            "content-type": "application/json",
            "x-github-event": "pull_request",
            "x-github-delivery": str(uuid4()),
            "x-hub-signature-256": sig,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
