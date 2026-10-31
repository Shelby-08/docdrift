from collections.abc import Callable

from github import Github, GithubIntegration, GithubRetry
from github.Auth import AppAuth

from docsentry.config import Settings
from docsentry.retrieval.errors import translate_github_exception

IntegrationFactory = Callable[[AppAuth, int], GithubIntegration]


class GitHubAuthService:
    """Service managing GitHub App authentication and caching installation clients."""

    def __init__(
        self,
        settings: Settings,
        integration_factory: IntegrationFactory | None = None,
    ) -> None:
        self._settings = settings
        self._integration_factory = integration_factory
        self._integration: GithubIntegration | None = None
        self._clients: dict[int, Github] = {}

    def _get_integration(self) -> GithubIntegration:
        if self._integration is None:
            app_auth = AppAuth(
                app_id=self._settings.github_app_id,
                private_key=self._settings.github_private_key.get_secret_value(),
            )
            if self._integration_factory is not None:
                self._integration = self._integration_factory(
                    app_auth,
                    self._settings.github_api_timeout_seconds,
                )
            else:
                retry = GithubRetry(total=0)
                self._integration = GithubIntegration(
                    auth=app_auth,
                    timeout=self._settings.github_api_timeout_seconds,
                    per_page=100,
                    retry=retry,
                )
        return self._integration

    def client_for_installation(self, installation_id: int) -> Github:
        """Return a cached or newly created Github client for an installation."""
        if installation_id in self._clients:
            return self._clients[installation_id]

        try:
            integration = self._get_integration()
            client = integration.get_github_for_installation(installation_id)
            self._clients[installation_id] = client
            return client
        except Exception as exc:
            raise translate_github_exception(exc, "client_for_installation") from exc
