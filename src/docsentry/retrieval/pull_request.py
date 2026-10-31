from typing import Any

from docsentry.models import PullRequestEventContext
from docsentry.retrieval.errors import InvalidRequest, translate_github_exception
from docsentry.retrieval.models import PullRequestContext


def fetch_pull_request(
    gh: Any,
    event: PullRequestEventContext,
) -> tuple[Any, Any, PullRequestContext]:
    """Fetch pull request and repository from GitHub API and construct context."""
    repo_full_name = f"{event.owner}/{event.repo}"
    try:
        repo = gh.get_repo(repo_full_name)
    except Exception as exc:
        raise translate_github_exception(exc, "get_repo") from exc

    if getattr(repo, "id", None) != event.repo_id:
        raise InvalidRequest(
            operation="verify_repo_id",
            message=f"Repository ID mismatch: expected {event.repo_id}",
        )

    try:
        pr = repo.get_pull(event.pr_number)
    except Exception as exc:
        raise translate_github_exception(exc, "get_pull") from exc

    api_head_sha = pr.head.sha
    superseded = api_head_sha.lower() != event.head_sha.lower()

    context = PullRequestContext(
        delivery_id=getattr(event, "delivery_id", ""),
        installation_id=event.installation_id,
        owner=event.owner,
        repository=event.repo,
        repository_id=event.repo_id,
        pull_number=event.pr_number,
        title=pr.title,
        html_url=pr.html_url,
        base_ref=pr.base.ref,
        head_ref=pr.head.ref,
        base_sha=pr.base.sha,
        head_sha=api_head_sha,
        merge_base_sha=None,
        state=pr.state,
        is_draft=bool(pr.draft),
        event_head_sha=event.head_sha,
        superseded_event=superseded,
    )
    return repo, pr, context


def resolve_merge_base(repo: Any, base_sha: str, head_sha: str) -> tuple[str, str | None]:
    """Resolve merge-base commit SHA between base and head."""
    try:
        comparison = repo.compare(base_sha, head_sha)
        merge_commit = getattr(comparison, "merge_base_commit", None)
        if merge_commit and getattr(merge_commit, "sha", None):
            return str(merge_commit.sha), None
        return base_sha, "merge_base_commit unavailable, fell back to base_sha"
    except Exception:
        return base_sha, "compare failed, fell back to base_sha"
