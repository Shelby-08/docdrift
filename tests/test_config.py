import pytest

from docsentry.config import ConfigError, load_settings


def test_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv(
        "GITHUB_PRIVATE_KEY",
        "-----BEGIN RSA PRIVATE KEY-----\\nFAKE\\n-----END RSA PRIVATE KEY-----",
    )
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "secret123")

    settings = load_settings(env_file=None)
    assert settings.github_app_id == "123"
    assert settings.port == 3000
    assert "\n" in settings.github_private_key.get_secret_value()


def test_missing_vars_throws(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_PRIVATE_KEY", raising=False)

    with pytest.raises(ConfigError) as exc_info:
        load_settings(env_file=None)

    assert "github_app_id" in str(exc_info.value)


def test_secret_redacted_in_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "SECRET_KEY")
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    with pytest.raises(ConfigError) as exc_info:
        load_settings(env_file=None)

    # Ensure the actual secret value is not in the error message
    assert "SECRET_KEY" not in str(exc_info.value)
    assert "github_webhook_secret" in str(exc_info.value)
