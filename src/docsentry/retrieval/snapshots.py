import base64
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from github import GithubException, UnknownObjectException

from docsentry.config import Settings
from docsentry.retrieval.errors import (
    JobSuperseded,
    translate_github_exception,
)
from docsentry.retrieval.models import (
    ChangedFile,
    FileSnapshot,
    FileVersion,
    RetrievalError,
    SkippedFile,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileReadResult:
    version: FileVersion | None = None
    skipped: SkippedFile | None = None
    missing: bool = False


def read_file_at_sha(
    repo: Any,
    path: str,
    sha: str,
    limits: Settings,
) -> FileReadResult:
    """Read and decode file at a specific git ref/commit SHA."""
    try:
        content_file = repo.get_contents(path, ref=sha)
    except (UnknownObjectException, GithubException) as exc:
        if getattr(exc, "status", None) == 404:
            return FileReadResult(missing=True)
        raise translate_github_exception(exc, f"read_file_at_sha:{path}") from exc
    except Exception as exc:
        raise translate_github_exception(exc, f"read_file_at_sha:{path}") from exc

    if isinstance(content_file, list):
        return FileReadResult(skipped=SkippedFile(path=path, commit_sha=sha, reason="directory"))

    content_type = getattr(content_file, "type", "file")
    if content_type == "submodule":
        return FileReadResult(skipped=SkippedFile(path=path, commit_sha=sha, reason="submodule"))
    if content_type == "symlink":
        return FileReadResult(skipped=SkippedFile(path=path, commit_sha=sha, reason="symlink"))
    if content_type != "file":
        return FileReadResult(
            skipped=SkippedFile(path=path, commit_sha=sha, reason="unsupported_type")
        )

    size = getattr(content_file, "size", 0) or 0
    if size > limits.max_file_bytes:
        return FileReadResult(
            skipped=SkippedFile(
                path=path,
                commit_sha=sha,
                reason="oversized",
                detail=f"{size} > {limits.max_file_bytes}",
            )
        )

    raw_content = getattr(content_file, "content", None)
    encoding = getattr(content_file, "encoding", None)

    if encoding == "base64" and raw_content is not None:
        try:
            raw_bytes = base64.b64decode(raw_content)
        except Exception:
            return FileReadResult(skipped=SkippedFile(path=path, commit_sha=sha, reason="error"))
    elif not raw_content and size > 0:
        return FileReadResult(skipped=SkippedFile(path=path, commit_sha=sha, reason="oversized"))
    elif isinstance(raw_content, str):
        raw_bytes = raw_content.encode("utf-8")
    elif isinstance(raw_content, bytes):
        raw_bytes = raw_content
    else:
        raw_bytes = b""

    if b"\x00" in raw_bytes[:8000]:
        return FileReadResult(skipped=SkippedFile(path=path, commit_sha=sha, reason="binary"))

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return FileReadResult(skipped=SkippedFile(path=path, commit_sha=sha, reason="not_utf8"))

    blob_sha = getattr(content_file, "sha", "") or "0" * 40
    if len(blob_sha) != 40:
        blob_sha = "0" * 40

    version = FileVersion(
        path=path,
        commit_sha=sha,
        blob_sha=blob_sha,
        size=len(raw_bytes),
        text=text,
    )
    return FileReadResult(version=version)


class GitHubFileReader:
    """Cached reader for repository files at specific commit SHAs."""

    def __init__(
        self,
        repo: Any,
        limits: Settings,
        reader_logger: logging.Logger | None = None,
    ) -> None:
        self._repo = repo
        self._limits = limits
        self._logger = reader_logger or logger
        self._cache: dict[tuple[str, str], FileReadResult] = {}

    def read(self, path: str, sha: str) -> FileReadResult:
        key = (sha.lower(), path)
        if key in self._cache:
            return self._cache[key]
        res = read_file_at_sha(self._repo, path, sha, self._limits)
        self._cache[key] = res
        return res


def plan_snapshots(
    changed: list[ChangedFile],
    limits: Settings,
) -> tuple[list[ChangedFile], list[SkippedFile]]:
    """Plan snapshot targets prioritizing doc and source, filtering unsupported and over budget."""
    skipped: list[SkippedFile] = []
    eligible: list[ChangedFile] = []

    for f in changed:
        if f.category in ("doc", "source", "config"):
            eligible.append(f)
        else:
            skipped.append(SkippedFile(path=f.filename, reason="unsupported_type"))

    docs = [f for f in eligible if f.category == "doc"]
    sources = [f for f in eligible if f.category == "source"]
    configs = [f for f in eligible if f.category == "config"]
    ordered = docs + sources + configs

    planned = ordered[: limits.max_snapshot_files]
    excess = ordered[limits.max_snapshot_files :]

    for f in excess:
        skipped.append(SkippedFile(path=f.filename, reason="over_budget"))

    return planned, skipped


@dataclass(frozen=True)
class SnapshotsResult:
    snapshots: list[FileSnapshot]
    skipped: list[SkippedFile]
    errors: list[RetrievalError]


def build_snapshots(
    repo: Any,
    planned: list[ChangedFile],
    merge_base_sha: str,
    head_sha: str,
    limits: Settings,
    exec_logger: logging.Logger | None = None,
    should_abort: Callable[[], bool] = lambda: False,
) -> SnapshotsResult:
    """Fetch before and after file snapshots sequentially within budget limits."""
    log = exec_logger or logger
    reader = GitHubFileReader(repo, limits, reader_logger=log)
    snapshots: list[FileSnapshot] = []
    skipped: list[SkippedFile] = []
    errors: list[RetrievalError] = []
    accumulated_bytes = 0

    for f in planned:
        if should_abort():
            raise JobSuperseded()

        if accumulated_bytes >= limits.max_total_snapshot_bytes:
            skipped.append(SkippedFile(path=f.filename, reason="over_budget"))
            continue

        status = f.status.lower()
        before_ver: FileVersion | None = None
        after_ver: FileVersion | None = None
        file_skipped = False

        # 1. Fetch before version if applicable
        if status in ("modified", "removed", "renamed"):
            before_path = (
                f.previous_filename if (status == "renamed" and f.previous_filename) else f.filename
            )
            res_before = reader.read(before_path, merge_base_sha)
            if res_before.missing:
                errors.append(
                    RetrievalError(
                        code="missing_snapshot",
                        operation="fetch_before",
                        message=f"Missing before file: {before_path}",
                        path=before_path,
                    )
                )
                skipped.append(
                    SkippedFile(path=before_path, commit_sha=merge_base_sha, reason="missing")
                )
                file_skipped = True
            elif res_before.skipped:
                skipped.append(res_before.skipped)
                file_skipped = True
            else:
                before_ver = res_before.version
                if before_ver:
                    accumulated_bytes += before_ver.size

        # 2. Fetch after version if applicable
        if not file_skipped and status in ("added", "modified", "renamed"):
            res_after = reader.read(f.filename, head_sha)
            if res_after.missing:
                errors.append(
                    RetrievalError(
                        code="missing_snapshot",
                        operation="fetch_after",
                        message=f"Missing after file: {f.filename}",
                        path=f.filename,
                    )
                )
                skipped.append(SkippedFile(path=f.filename, commit_sha=head_sha, reason="missing"))
                file_skipped = True
            elif res_after.skipped:
                skipped.append(res_after.skipped)
                file_skipped = True
            else:
                after_ver = res_after.version
                if after_ver:
                    accumulated_bytes += after_ver.size

        if not file_skipped:
            snapshot = FileSnapshot(
                path=f.filename,
                previous_path=f.previous_filename if status == "renamed" else None,
                status=status,
                before=before_ver,
                after=after_ver,
            )
            snapshots.append(snapshot)

    return SnapshotsResult(snapshots=snapshots, skipped=skipped, errors=errors)
