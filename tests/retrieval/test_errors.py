import requests
from github import (
    BadCredentialsException,
    GithubException,
    RateLimitExceededException,
    UnknownObjectException,
)

from docsentry.retrieval.errors import (
    AuthenticationFailure,
    InstallationUnavailable,
    InvalidRequest,
    PermissionDenied,
    RateLimited,
    RequestConflict,
    ResourceNotFound,
    TransientFailure,
    translate_github_exception,
)


def test_translate_bad_credentials() -> None:
    exc = BadCredentialsException(status=401, data={"message": "Bad credentials"}, headers=None)
    failure = translate_github_exception(exc, "auth")
    assert isinstance(failure, AuthenticationFailure)
    assert failure.retryable is False
    assert failure.code == "authentication_failure"
    assert "Bad credentials" not in str(failure)
    assert "status 401" in str(failure)


def test_translate_permission_denied() -> None:
    exc = GithubException(status=403, data={"message": "Must have admin rights"}, headers=None)
    failure = translate_github_exception(exc, "get_repo")
    assert isinstance(failure, PermissionDenied)
    assert failure.retryable is False
    assert failure.code == "permission_denied"
    assert "Must have admin rights" not in str(failure)


def test_translate_rate_limit_exceeded() -> None:
    exc = RateLimitExceededException(status=403, data={"message": "API rate limit exceeded"}, headers={"x-ratelimit-remaining": "0"})
    failure = translate_github_exception(exc, "get_pull")
    assert isinstance(failure, RateLimited)
    assert failure.retryable is True
    assert failure.code == "rate_limited"


def test_translate_429_rate_limit_with_retry_after() -> None:
    exc = GithubException(status=429, data={"message": "Too many requests"}, headers={"retry-after": "60"})
    failure = translate_github_exception(exc, "get_contents")
    assert isinstance(failure, RateLimited)
    assert failure.retry_after_seconds == 60


def test_translate_not_found_resource() -> None:
    exc = UnknownObjectException(status=404, data={"message": "Not found"}, headers=None)
    failure = translate_github_exception(exc, "get_pull")
    assert isinstance(failure, ResourceNotFound)
    assert failure.retryable is False


def test_translate_not_found_installation() -> None:
    exc = UnknownObjectException(status=404, data={"message": "Not found"}, headers=None)
    failure = translate_github_exception(exc, "get_installation")
    assert isinstance(failure, InstallationUnavailable)
    assert failure.retryable is False


def test_translate_conflict_and_invalid() -> None:
    exc_conflict = GithubException(status=409, data=None, headers=None)
    assert isinstance(translate_github_exception(exc_conflict, "op"), RequestConflict)

    exc_invalid = GithubException(status=422, data=None, headers=None)
    assert isinstance(translate_github_exception(exc_invalid, "op"), InvalidRequest)


def test_translate_500_and_network_timeouts() -> None:
    exc_500 = GithubException(status=502, data=None, headers=None)
    failure_500 = translate_github_exception(exc_500, "op")
    assert isinstance(failure_500, TransientFailure)
    assert failure_500.retryable is True

    timeout_exc = requests.exceptions.ConnectTimeout("Connection timed out")
    failure_timeout = translate_github_exception(timeout_exc, "op")
    assert isinstance(failure_timeout, TransientFailure)
    assert failure_timeout.retryable is True
