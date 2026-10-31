import pytest
from github import GithubException, UnknownObjectException

from docsentry.models import PullRequestEventContext
from docsentry.retrieval.errors import (
    InvalidRequest,
    PermissionDenied,
    RateLimited,
    ResourceNotFound,
)
from docsentry.retrieval.pull_request import fetch_pull_request, resolve_merge_base
from tests.retrieval.fakes import FakeGithub, FakePullRequest, FakeRepo

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def make_event(
    repo_id: int = 123,
    head_sha: str = SHA_B,
) -> PullRequestEventContext:
    return PullRequestEventContext(
        action="opened",
        owner="org",
        repo="repo",
        repo_id=repo_id,
        pr_number=1,
        installation_id=456,
        base_sha=SHA_A,
        head_sha=head_sha,
        title="Test PR",
    )


def test_fetch_pull_request_valid() -> None:
    pr = FakePullRequest(head_sha=SHA_B)
    repo = FakeRepo(repo_id=123, pr=pr)
    gh = FakeGithub(repo=repo)
    event = make_event()

    r, p, ctx = fetch_pull_request(gh, event)
    assert r is repo
    assert p is pr
    assert ctx.head_sha == SHA_B
    assert ctx.superseded_event is False


def test_fetch_pull_request_stale_event() -> None:
    pr = FakePullRequest(head_sha=SHA_C)
    repo = FakeRepo(repo_id=123, pr=pr)
    gh = FakeGithub(repo=repo)
    event = make_event(head_sha=SHA_B)

    _, _, ctx = fetch_pull_request(gh, event)
    assert ctx.head_sha == SHA_C
    assert ctx.event_head_sha == SHA_B
    assert ctx.superseded_event is True


def test_fetch_pull_request_repo_id_mismatch() -> None:
    repo = FakeRepo(repo_id=999)
    gh = FakeGithub(repo=repo)
    event = make_event(repo_id=123)

    with pytest.raises(InvalidRequest) as exc_info:
        fetch_pull_request(gh, event)
    assert "Repository ID mismatch" in str(exc_info.value)


def test_fetch_pull_request_permission_and_not_found() -> None:
    class ErrorGithub:
        def __init__(self, exc: Exception) -> None:
            self.exc = exc

        def get_repo(self, name: str) -> None:
            raise self.exc

    event = make_event()
    with pytest.raises(PermissionDenied):
        fetch_pull_request(ErrorGithub(GithubException(403, {"msg": "forbidden"})), event)

    with pytest.raises(ResourceNotFound):
        fetch_pull_request(ErrorGithub(UnknownObjectException(404, {"msg": "not found"})), event)

    with pytest.raises(RateLimited):
        headers = {"x-ratelimit-remaining": "0"}
        fetch_pull_request(ErrorGithub(GithubException(403, None, headers=headers)), event)


def test_resolve_merge_base() -> None:
    repo = FakeRepo(merge_base_sha=SHA_A)
    sha, warn = resolve_merge_base(repo, SHA_A, SHA_B)
    assert sha == SHA_A
    assert warn is None

    repo_none = FakeRepo(merge_base_sha=None)
    sha2, warn2 = resolve_merge_base(repo_none, SHA_A, SHA_B)
    assert sha2 == SHA_A
    assert warn2 is not None
    assert "merge_base_commit unavailable" in warn2

    class FailingRepo:
        def compare(self, base: str, head: str) -> None:
            raise RuntimeError("comparison error")

    sha3, warn3 = resolve_merge_base(FailingRepo(), SHA_A, SHA_B)
    assert sha3 == SHA_A
    assert warn3 is not None
    assert "compare failed" in warn3
