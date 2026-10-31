from dataclasses import dataclass
from typing import Any

from docsentry.retrieval.classify import classify_path
from docsentry.retrieval.errors import translate_github_exception
from docsentry.retrieval.models import ChangedFile


@dataclass(frozen=True)
class ChangedFilesResult:
    files: list[ChangedFile]
    complete: bool
    reported_total: int | None


def list_changed_files(pr: Any, *, hard_cap: int = 3000) -> ChangedFilesResult:
    """List all changed files in a pull request with pagination handling."""
    reported_total: int | None = getattr(pr, "changed_files", None)
    files: list[ChangedFile] = []

    try:
        paginated_files = pr.get_files()
        for f in paginated_files:
            cat = classify_path(f.filename)
            raw_sha = getattr(f, "sha", None) or "0" * 40
            file_model = ChangedFile(
                filename=f.filename,
                previous_filename=getattr(f, "previous_filename", None),
                status=f.status,
                additions=f.additions,
                deletions=f.deletions,
                changes=f.changes,
                blob_sha=raw_sha,
                patch=getattr(f, "patch", None),
                raw_url=None,
                category=cat,
            )
            files.append(file_model)
            if len(files) >= hard_cap:
                break
    except Exception as exc:
        raise translate_github_exception(exc, "list_changed_files") from exc

    if reported_total is None:
        complete = False
    elif reported_total > hard_cap:
        complete = False
    else:
        complete = len(files) == reported_total

    return ChangedFilesResult(
        files=files,
        complete=complete,
        reported_total=reported_total,
    )
