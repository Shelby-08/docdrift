from typing import Any

from docsentry.config import Settings
from docsentry.models import PullRequestEventContext
from docsentry.retrieval.bundle_builder import build_pull_request_bundle
from tests.retrieval.fakes import (
    FakeGitTree,
    FakeGitTreeElement,
    FakePullRequest,
    FakeRepo,
)

SHA_BASE = "a" * 40
SHA_HEAD = "b" * 40
SHA_TREE = "e" * 40
SHA_BLOB = "1" * 40


def make_settings() -> Settings:
    return Settings(
        github_app_id="123",
        github_private_key="key",
        github_webhook_secret="sec",
    )


class FakeGithub:
    def __init__(self, repo: FakeRepo) -> None:
        self.repo = repo

    def get_repo(self, full_name_or_id: Any) -> FakeRepo:
        return self.repo


def test_bundle_builder_full_flow() -> None:
    repo = FakeRepo(
        pr=FakePullRequest(
            base_sha=SHA_BASE,
            head_sha=SHA_HEAD,
        ),
        merge_base_sha=SHA_BASE,
    )
    tree_elems = [FakeGitTreeElement(path="README.md", element_type="blob", sha=SHA_BLOB)]
    repo.tree_map[(SHA_BASE, True)] = FakeGitTree(tree=tree_elems)
    repo.tree_map[(SHA_HEAD, True)] = FakeGitTree(tree=tree_elems)

    gh = FakeGithub(repo)
    ctx = PullRequestEventContext(
        action="opened",
        owner="org",
        repo="repo",
        repo_id=1,
        installation_id=10,
        pr_number=42,
        base_sha=SHA_BASE,
        head_sha=SHA_HEAD,
        title="Test PR",
        delivery_id="d1",
    )

    bundle = build_pull_request_bundle(gh, ctx, make_settings())
    assert bundle.context.pr_number == 42
    assert bundle.context.base_sha == SHA_BASE
    assert bundle.context.head_sha == SHA_HEAD
    assert bundle.context.merge_base_sha == SHA_BASE
    assert bundle.base_index.complete is True
    assert bundle.head_index.complete is True
    assert bundle.errors == []
    assert bundle.warnings == []
