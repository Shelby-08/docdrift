from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docsentry.models import PullRequestEventContext


class _RepositoryOwnerModel(BaseModel):
    model_config = ConfigDict(strict=True)
    login: str = Field(..., min_length=1)


class _PullRequestBaseModel(BaseModel):
    model_config = ConfigDict(strict=True)
    sha: str = Field(..., pattern=r"^[0-9a-fA-F]{40}$")


class _PullRequestModel(BaseModel):
    model_config = ConfigDict(strict=True)
    number: int = Field(..., gt=0)
    title: str = Field(..., min_length=1)
    base: _PullRequestBaseModel
    head: _PullRequestBaseModel


class _RepositoryModel(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int = Field(..., gt=0)
    name: str = Field(..., min_length=1)
    owner: _RepositoryOwnerModel


class _InstallationModel(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int = Field(..., gt=0)


class _PayloadModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    action: Literal["opened", "synchronize", "reopened"]
    installation: _InstallationModel
    repository: _RepositoryModel
    pull_request: _PullRequestModel


@dataclass(frozen=True)
class ExtractionFailure:
    fields: list[str]


def extract_pull_request_context(payload: object) -> PullRequestEventContext | ExtractionFailure:
    if not isinstance(payload, dict):
        return ExtractionFailure(fields=["payload must be object"])

    copy: dict[str, object] = dict(payload)
    if "installation" not in copy:
        copy["installation"] = {}
    if "repository" not in copy:
        copy["repository"] = {"owner": {}}
    elif isinstance(copy["repository"], dict) and "owner" not in copy["repository"]:
        copy["repository"] = {**copy["repository"], "owner": {}}
    if "pull_request" not in copy:
        copy["pull_request"] = {"base": {}, "head": {}}
    elif isinstance(copy["pull_request"], dict):
        pr = dict(copy["pull_request"])
        if "base" not in pr:
            pr["base"] = {}
        if "head" not in pr:
            pr["head"] = {}
        copy["pull_request"] = pr

    try:
        model = _PayloadModel.model_validate(copy)
        return PullRequestEventContext(
            action=model.action,
            owner=model.repository.owner.login,
            repo=model.repository.name,
            repo_id=model.repository.id,
            pr_number=model.pull_request.number,
            installation_id=model.installation.id,
            base_sha=model.pull_request.base.sha,
            head_sha=model.pull_request.head.sha,
            title=model.pull_request.title,
        )
    except ValidationError as e:
        fields = [".".join(str(p) for p in err["loc"]) for err in e.errors()]
        return ExtractionFailure(fields=fields)
