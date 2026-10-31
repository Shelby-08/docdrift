from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class PullRequestEventContext:
    action: str
    owner: str
    repo: str
    repo_id: int
    pr_number: int
    installation_id: int
    base_sha: str
    head_sha: str
    title: str


PullRequestHandler = Callable[[PullRequestEventContext], Awaitable[None]]
