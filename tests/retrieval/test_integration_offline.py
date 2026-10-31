import base64
from typing import Any

from docsentry.config import Settings
from docsentry.models import PullRequestEventContext
from docsentry.retrieval.bundle_builder import build_pull_request_bundle
from tests.retrieval.fakes import (
    FakeContentFile,
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


class FakeGithubClient:
    def __init__(self, repo: FakeRepo) -> None:
        self.repo = repo

    def get_repo(self, name_or_id: Any) -> FakeRepo:
        return self.repo


def test_full_pipeline_offline_integration() -> None:
    repo = FakeRepo(
        pr=FakePullRequest(base_sha=SHA_BASE, head_sha=SHA_HEAD),
        merge_base_sha=SHA_BASE,
    )

    # File contents
    doc_content = base64.b64encode(b"# Architecture Guide\n\nSystem details.").decode("ascii")
    repo.contents_map[("docs/guide.md", SHA_HEAD)] = FakeContentFile(
        path="docs/guide.md", content=doc_content, size=35
    )

    # Tree
    elements = [
        FakeGitTreeElement(path="docs/guide.md", element_type="blob", sha=SHA_BLOB, size=35),
        FakeGitTreeElement(path="src/main.py", element_type="blob", sha=SHA_BLOB, size=100),
    ]
    repo.tree_map[(SHA_BASE, True)] = FakeGitTree(tree=elements)
    repo.tree_map[(SHA_HEAD, True)] = FakeGitTree(tree=elements)

    gh = FakeGithubClient(repo)
    event = PullRequestEventContext(
        action="opened",
        owner="my-org",
        repo="my-repo",
        repo_id=999,
        installation_id=42,
        pr_number=7,
        base_sha=SHA_BASE,
        head_sha=SHA_HEAD,
        title="Add guide",
        delivery_id="del-101",
    )

    bundle = build_pull_request_bundle(gh, event, make_settings())

    assert bundle.context.repo_full_name == "my-org/my-repo"
    assert bundle.context.pr_number == 7
    assert bundle.context.merge_base_sha == SHA_BASE
    assert bundle.base_index.complete is True
    assert bundle.head_index.complete is True
    assert len(bundle.base_index.entries) == 2
    assert len(bundle.head_index.entries) == 2
    assert bundle.errors == []
    assert bundle.warnings == []
