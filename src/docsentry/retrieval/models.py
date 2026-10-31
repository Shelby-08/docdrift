import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from docsentry.retrieval.classify import Category

SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")

SkippedReason = Literal[
    "oversized",
    "binary",
    "not_utf8",
    "unsupported_type",
    "submodule",
    "symlink",
    "directory",
    "over_budget",
    "missing",
    "error",
]


def _validate_sha(v: str) -> str:
    if not SHA_PATTERN.match(v):
        raise ValueError(f"Invalid SHA format: {v}")
    return v.lower()


class PullRequestContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    delivery_id: str
    installation_id: int = Field(gt=0)
    owner: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    repository_id: int = Field(gt=0)
    pull_number: int = Field(gt=0)
    title: str
    html_url: str
    base_ref: str
    head_ref: str
    base_sha: str
    head_sha: str
    merge_base_sha: str | None = None
    state: str
    is_draft: bool
    event_head_sha: str
    superseded_event: bool = False

    @field_validator("base_sha", "head_sha", "event_head_sha", mode="after")
    @classmethod
    def validate_required_shas(cls, v: str) -> str:
        return _validate_sha(v)

    @field_validator("merge_base_sha", mode="after")
    @classmethod
    def validate_optional_sha(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_sha(v)
        return None


class ChangedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    filename: str
    previous_filename: str | None = None
    status: str
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changes: int = Field(ge=0)
    blob_sha: str
    patch: str | None = None
    raw_url: str | None = None
    category: Category


class FileVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    commit_sha: str
    blob_sha: str
    size: int = Field(ge=0)
    text: str

    @field_validator("commit_sha", mode="after")
    @classmethod
    def validate_commit_sha(cls, v: str) -> str:
        return _validate_sha(v)


class FileSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    previous_path: str | None = None
    status: str
    before: FileVersion | None = None
    after: FileVersion | None = None


class SkippedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    commit_sha: str | None = None
    reason: SkippedReason
    detail: str | None = None

    @field_validator("commit_sha", mode="after")
    @classmethod
    def validate_opt_sha(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_sha(v)
        return None


class RetrievalError(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    operation: str
    message: str
    path: str | None = None
    retryable: bool = False


class RepositoryFileEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    type: str
    mode: str
    blob_sha: str
    size: int | None = None
    commit_sha: str
    category: Category

    @field_validator("commit_sha", mode="after")
    @classmethod
    def validate_commit_sha(cls, v: str) -> str:
        return _validate_sha(v)


class RepositoryFileIndex(BaseModel):
    model_config = ConfigDict(frozen=True)

    commit_sha: str
    entries: list[RepositoryFileEntry]
    complete: bool
    truncated_recursive: bool = False
    incomplete_reasons: list[str] = Field(default_factory=list)

    @field_validator("commit_sha", mode="after")
    @classmethod
    def validate_commit_sha(cls, v: str) -> str:
        return _validate_sha(v)


class PullRequestBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    context: PullRequestContext
    changed_files: list[ChangedFile]
    changed_files_complete: bool
    reported_changed_files: int | None = None
    snapshots: list[FileSnapshot]
    skipped_files: list[SkippedFile]
    base_index: RepositoryFileIndex
    head_index: RepositoryFileIndex
    errors: list[RetrievalError]
    warnings: list[str] = Field(default_factory=list)
    retrieved_at: str

    def unchanged_doc_paths(self) -> list[str]:
        changed_names: set[str] = set()
        for f in self.changed_files:
            changed_names.add(f.filename)
            if f.previous_filename:
                changed_names.add(f.previous_filename)

        unchanged: list[str] = []
        for entry in self.head_index.entries:
            if entry.category == "doc" and entry.path not in changed_names:
                unchanged.append(entry.path)
        return sorted(unchanged)

    def is_complete(self) -> bool:
        if not self.changed_files_complete:
            return False
        if not self.base_index.complete or not self.head_index.complete:
            return False
        has_fatal_errors = any(err.code != "warning" for err in self.errors)
        return not has_fatal_errors
