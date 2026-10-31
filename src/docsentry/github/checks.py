"""GitHub Checks adapter. The ONLY writes DocSentry performs: one Check Run per exact head SHA."""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from github import Github, GithubException, RateLimitExceededException

from docsentry.reporting.check_run import CheckRunReport

BATCH = 50


def external_id(repo_id: int, pr_number: int, head_sha: str) -> str:
    raw = f"{repo_id}:{pr_number}:{head_sha.lower()}"
    return "docsentry-" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def map_error(exc: Exception, creating: bool = False) -> str:
    """Map a PyGithub exception to a short safe code. Never includes exception text."""
    if isinstance(exc, RateLimitExceededException):
        return "github_rate_limited"
    if isinstance(exc, GithubException):
        if exc.status == 401:
            return "github_auth_failed"
        if exc.status == 403:
            return "github_checks_permission_missing"
        if creating and exc.status in (404, 422):
            return "github_check_unavailable_for_head"
        return "github_check_publish_failed"
    return "github_check_publish_failed"


@dataclass
class CheckHandle:
    run: Any
    head_sha: str
    ext_id: str


@dataclass(frozen=True)
class PublishOutcome:
    status: str  # published | failed | unavailable | cancelled
    code: str | None = None
    annotations_sent: int = 0
    annotations_dropped: bool = False


class CheckRunPublisher:
    def __init__(self, name: str, log: logging.Logger | None = None) -> None:
        self._name = name
        self._log = log or logging.getLogger(__name__)
        self._locks: dict[tuple[int, int, str], asyncio.Lock] = {}

    # ---- sync core (runs in a worker thread) ----
    def _begin(
        self, client: Github, owner: str, repo_name: str, repo_id: int, pr: int, head_sha: str
    ) -> CheckHandle:
        repo = client.get_repo(f"{owner}/{repo_name}")
        ext = external_id(repo_id, pr, head_sha)
        for run in repo.get_commit(head_sha).get_check_runs(check_name=self._name):
            if run.external_id == ext and run.head_sha.lower() == head_sha.lower():
                return CheckHandle(run, head_sha, ext)
        run = repo.create_check_run(
            name=self._name,
            head_sha=head_sha,
            external_id=ext,
            status="in_progress",
            started_at=datetime.now(UTC),
            output={"title": "DocSentry analysis in progress", "summary": "Analysis running."},
        )
        return CheckHandle(run, head_sha, ext)

    def _finish(self, h: CheckHandle, report: CheckRunReport) -> PublishOutcome:
        anns = [a.model_dump() for a in report.annotations]
        batches = [anns[i : i + BATCH] for i in range(0, len(anns), BATCH)] or [[]]
        base_out = {"title": report.title, "summary": report.summary}
        dropped = False
        sent = 0
        for i, batch in enumerate(batches):
            out: dict[str, Any] = dict(base_out)
            if batch:
                out["annotations"] = batch
            kwargs: dict[str, Any] = {"output": out}
            if i == 0:
                kwargs.update(
                    status="completed",
                    conclusion=report.conclusion,
                    completed_at=datetime.now(UTC),
                )
            try:
                h.run.edit(**kwargs)
                sent += len(batch)
            except GithubException as exc:
                if exc.status == 422 and batch:  # bad annotation: retry once without it
                    dropped = True
                    kwargs["output"] = dict(base_out)
                    h.run.edit(**kwargs)
                else:
                    raise
        return PublishOutcome("published", None, sent, dropped)

    def _cancel(self, h: CheckHandle) -> None:
        h.run.edit(
            status="completed",
            conclusion="cancelled",
            completed_at=datetime.now(UTC),
            output={"title": "Superseded", "summary": "A newer commit was pushed."},
        )

    # ---- async wrappers (all blocking calls off-loop) ----
    def _lock(self, key: tuple[int, int, str]) -> asyncio.Lock:
        if len(self._locks) > 256:
            self._locks = {k: v for k, v in self._locks.items() if v.locked()}
        return self._locks.setdefault(key, asyncio.Lock())

    async def begin(
        self, client: Github, owner: str, repo_name: str, repo_id: int, pr: int, head_sha: str
    ) -> tuple[CheckHandle | None, PublishOutcome | None]:
        async with self._lock((repo_id, pr, head_sha.lower())):
            try:
                h = await asyncio.to_thread(
                    self._begin, client, owner, repo_name, repo_id, pr, head_sha
                )
                return h, None
            except Exception as exc:  # adapter boundary: map to a safe code only
                code = map_error(exc, creating=True)
                self._log.warning("check_begin_failed code=%s pr=%d", code, pr)
                st = "unavailable" if code == "github_check_unavailable_for_head" else "failed"
                return None, PublishOutcome(st, code)

    async def finish(
        self, h: CheckHandle, report: CheckRunReport, repo_id: int, pr: int
    ) -> PublishOutcome:
        async with self._lock((repo_id, pr, h.head_sha.lower())):
            try:
                out = await asyncio.to_thread(self._finish, h, report)
            except Exception as exc:
                code = map_error(exc)
                self._log.warning("check_finish_failed code=%s pr=%d", code, pr)
                return PublishOutcome("failed", code)
            return out

    async def cancel(self, h: CheckHandle, repo_id: int, pr: int) -> PublishOutcome:
        async with self._lock((repo_id, pr, h.head_sha.lower())):
            try:
                await asyncio.to_thread(self._cancel, h)
            except Exception as exc:
                return PublishOutcome("failed", map_error(exc))
            return PublishOutcome("cancelled")
