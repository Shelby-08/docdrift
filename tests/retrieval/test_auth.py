import pytest
from github import BadCredentialsException, UnknownObjectException

from docsentry.config import Settings
from docsentry.retrieval.auth import GitHubAuthService
from docsentry.retrieval.errors import AuthenticationFailure, InstallationUnavailable
from tests.retrieval.fakes import FakeGithub, FakeIntegration


def make_test_settings() -> Settings:
    return Settings(
        github_app_id="12345",
        github_private_key="test-private-key",
        github_webhook_secret="test-secret",
    )


def test_auth_service_reuses_client() -> None:
    settings = make_test_settings()
    fake_gh = FakeGithub()
    fake_integration = FakeIntegration(client=fake_gh)

    service = GitHubAuthService(
        settings=settings,
        integration_factory=lambda auth, timeout: fake_integration,  # type: ignore[return-value]
    )

    c1 = service.client_for_installation(42)
    c2 = service.client_for_installation(42)

    assert c1 is c2
    assert fake_integration.calls == [42]


def test_auth_service_bad_credentials() -> None:
    settings = make_test_settings()

    def failing_factory(auth: object, timeout: int) -> object:
        class FailingIntegration:
            def get_github_for_installation(self, installation_id: int, **kwargs: object) -> object:
                raise BadCredentialsException(status=401, data={"message": "Bad credentials"})

        return FailingIntegration()

    service = GitHubAuthService(settings=settings, integration_factory=failing_factory)  # type: ignore[arg-type]

    with pytest.raises(AuthenticationFailure) as exc_info:
        service.client_for_installation(99)
    assert "status 401" in str(exc_info.value)
    assert "test-private-key" not in str(exc_info.value)


def test_auth_service_installation_unavailable() -> None:
    settings = make_test_settings()

    def missing_factory(auth: object, timeout: int) -> object:
        class MissingIntegration:
            def get_github_for_installation(self, installation_id: int, **kwargs: object) -> object:
                raise UnknownObjectException(status=404, data={"message": "Not found"})

        return MissingIntegration()

    service = GitHubAuthService(settings=settings, integration_factory=missing_factory)  # type: ignore[arg-type]

    with pytest.raises(InstallationUnavailable) as exc_info:
        service.client_for_installation(99)
    assert "status 404 (installation unavailable)" in str(exc_info.value)
