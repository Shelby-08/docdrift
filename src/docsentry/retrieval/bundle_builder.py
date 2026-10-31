import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from docsentry.config import Settings
from docsentry.models import PullRequestEventContext
from docsentry.retrieval.changed_files import list_changed_files
from docsentry.retrieval.errors import (
    AuthenticationFailure,
    InstallationUnavailable,
    JobSuperseded,
    PermissionDenied,
    RateLimited,
    ResourceNotFound,
)
from docsentry.retrieval.models import (
    PullRequestBundle,
    RepositoryFileIndex,
    RetrievalError,
)
from docsentry.retrieval.pull_request import fetch_pull_request, resolve_merge_base
from docsentry.retrieval.repository_tree import build_repository_index
from docsentry.retrieval.snapshots import build_snapshots, plan_snapshots

logger = logging.getLogger(__name__)


def build_pull_request_bundle(
    gh: Any,
    event: PullRequestEventContext,
    settings: Settings,
    build_logger: logging.Logger | None = None,
    should_abort: Callable[[], bool] = lambda: False,
) -> PullRequestBundle:
    """Synchronously build a full normalized pull request bundle using PyGithub."""
    log = build_logger or logger
    if should_abort():
        raise JobSuperseded()

    warnings: list[str] = []
    errors: list[RetrievalError] = []

    # 1. Fetch pull request & base context
    repo, pr, context = fetch_pull_request(gh, event)
    if context.superseded_event:
        warnings.append(f"superseded_event: bundle built for current API head {context.head_sha}")
    if should_abort():
        raise JobSuperseded()

    # 2. Resolve merge base
    merge_base_sha, mb_warn = resolve_merge_base(repo, context.base_sha, context.head_sha)
    context = context.model_copy(update={"merge_base_sha": merge_base_sha})
    if mb_warn:
        warnings.append(mb_warn)
    if should_abort():
        raise JobSuperseded()

    # 3. List changed files
    changed_res = list_changed_files(pr)
    if should_abort():
        raise JobSuperseded()

    # 4. Plan and build snapshots
    planned, skipped_plan = plan_snapshots(changed_res.files, settings)
    snapshots_res = build_snapshots(
        repo,
        planned,
        merge_base_sha,
        context.head_sha,
        settings,
        exec_logger=log,
        should_abort=should_abort,
    )
    all_skipped = skipped_plan + snapshots_res.skipped
    errors.extend(snapshots_res.errors)
    if should_abort():
        raise JobSuperseded()

    # 5. Build repository tree indices
    try:
        base_index = build_repository_index(repo, merge_base_sha, settings, tree_logger=log)
    except (
        AuthenticationFailure,
        InstallationUnavailable,
        PermissionDenied,
        RateLimited,
        ResourceNotFound,
    ):
        raise
    except Exception as exc:
        errors.append(
            RetrievalError(
                code="base_index_error",
                operation="build_base_index",
                message=f"Failed base index: {type(exc).__name__}",
            )
        )
        base_index = RepositoryFileIndex(
            commit_sha=merge_base_sha,
            entries=[],
            complete=False,
            incomplete_reasons=[str(exc)],
        )

    if should_abort():
        raise JobSuperseded()

    try:
        head_index = build_repository_index(repo, context.head_sha, settings, tree_logger=log)
    except (
        AuthenticationFailure,
        InstallationUnavailable,
        PermissionDenied,
        RateLimited,
        ResourceNotFound,
    ):
        raise
    except Exception as exc:
        errors.append(
            RetrievalError(
                code="head_index_error",
                operation="build_head_index",
                message=f"Failed head index: {type(exc).__name__}",
            )
        )
        head_index = RepositoryFileIndex(
            commit_sha=context.head_sha,
            entries=[],
            complete=False,
            incomplete_reasons=[str(exc)],
        )

    retrieved_at = datetime.now(UTC).isoformat()

    bundle = PullRequestBundle(
        context=context,
        changed_files=changed_res.files,
        changed_files_complete=changed_res.complete,
        reported_changed_files=changed_res.reported_total,
        snapshots=snapshots_res.snapshots,
        skipped_files=all_skipped,
        base_index=base_index,
        head_index=head_index,
        errors=errors,
        warnings=warnings,
        retrieved_at=retrieved_at,
    )
    return bundle
