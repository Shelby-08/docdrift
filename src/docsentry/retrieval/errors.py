from datetime import datetime

from github import GithubException, RateLimitExceededException


class GitHubRetrievalFailure(Exception):
    """Base exception for all GitHub data retrieval failures."""

    def __init__(self, code: str, operation: str, retryable: bool = False, message: str | None = None) -> None:
        self.code = code
        self.operation = operation
        self.retryable = retryable
        msg = message or f"{operation}: {code}"
        super().__init__(msg)


class AuthenticationFailure(GitHubRetrievalFailure):
    def __init__(self, operation: str, message: str | None = None) -> None:
        super().__init__(code="authentication_failure", operation=operation, retryable=False, message=message)


class InstallationUnavailable(GitHubRetrievalFailure):
    def __init__(self, operation: str, message: str | None = None) -> None:
        super().__init__(code="installation_unavailable", operation=operation, retryable=False, message=message)


class PermissionDenied(GitHubRetrievalFailure):
    def __init__(self, operation: str, message: str | None = None) -> None:
        super().__init__(code="permission_denied", operation=operation, retryable=False, message=message)


class RateLimited(GitHubRetrievalFailure):
    def __init__(
        self,
        operation: str,
        reset_at: datetime | None = None,
        retry_after_seconds: int | None = None,
        message: str | None = None,
    ) -> None:
        self.reset_at = reset_at
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code="rate_limited", operation=operation, retryable=True, message=message)


class ResourceNotFound(GitHubRetrievalFailure):
    def __init__(self, operation: str, message: str | None = None) -> None:
        super().__init__(code="not_found", operation=operation, retryable=False, message=message)


class RequestConflict(GitHubRetrievalFailure):
    def __init__(self, operation: str, message: str | None = None) -> None:
        super().__init__(code="conflict", operation=operation, retryable=False, message=message)


class InvalidRequest(GitHubRetrievalFailure):
    def __init__(self, operation: str, message: str | None = None) -> None:
        super().__init__(code="invalid_request", operation=operation, retryable=False, message=message)


class TransientFailure(GitHubRetrievalFailure):
    def __init__(self, operation: str, message: str | None = None) -> None:
        super().__init__(code="transient_failure", operation=operation, retryable=True, message=message)


class JobSuperseded(GitHubRetrievalFailure):
    def __init__(self, operation: str = "job", message: str | None = None) -> None:
        super().__init__(code="job_superseded", operation=operation, retryable=False, message=message or "Job superseded by newer commit")


def translate_github_exception(exc: Exception, operation: str) -> GitHubRetrievalFailure:
    """Translate PyGithub/HTTP exceptions to safe typed DocSentry failures."""
    if isinstance(exc, RateLimitExceededException):
        return RateLimited(operation=operation, message=f"{operation} failed: status 403 (rate limited)")

    if isinstance(exc, GithubException):
        status = exc.status
        headers = exc.headers or {}
        msg_raw = str(exc.data) if exc.data else ""
        is_rate_limit = (
            status in (403, 429)
            and (
                headers.get("x-ratelimit-remaining") == "0"
                or "retry-after" in headers
                or "rate limit" in msg_raw.lower()
            )
        )
        if is_rate_limit:
            retry_after: int | None = None
            if "retry-after" in headers:
                try:
                    retry_after = int(headers["retry-after"])
                except (ValueError, TypeError):
                    pass
            return RateLimited(operation=operation, retry_after_seconds=retry_after, message=f"{operation} failed: status {status} (rate limited)")

        if status == 401:
            return AuthenticationFailure(operation=operation, message=f"{operation} failed: status 401")
        if status == 403:
            return PermissionDenied(operation=operation, message=f"{operation} failed: status 403")
        if status == 404:
            if "installation" in operation.lower():
                return InstallationUnavailable(operation=operation, message=f"{operation} failed: status 404 (installation unavailable)")
            return ResourceNotFound(operation=operation, message=f"{operation} failed: status 404")
        if status == 409:
            return RequestConflict(operation=operation, message=f"{operation} failed: status 409")
        if status == 422:
            return InvalidRequest(operation=operation, message=f"{operation} failed: status 422")
        if status >= 500:
            return TransientFailure(operation=operation, message=f"{operation} failed: status {status}")

        return GitHubRetrievalFailure(code=f"github_status_{status}", operation=operation, message=f"{operation} failed: status {status}")

    exc_name = type(exc).__name__
    if "Timeout" in exc_name or "Connection" in exc_name:
        return TransientFailure(operation=operation, message=f"{operation} failed: {exc_name}")

    return GitHubRetrievalFailure(code="unexpected_retrieval_failure", operation=operation, message=f"{operation} failed: {exc_name}")
