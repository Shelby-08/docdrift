from github import UnknownObjectException

from docsentry.config import Settings
from docsentry.retrieval.repository_tree import build_repository_index
from tests.retrieval.fakes import FakeGitTree, FakeGitTreeElement, FakeRepo

SHA_TREE = "e" * 40
SHA_SUBTREE = "f" * 40
SHA_BLOB = "1" * 40


def make_settings(max_tree_requests: int = 200) -> Settings:
    return Settings(
        github_app_id="123",
        github_private_key="key",
        github_webhook_secret="sec",
        max_tree_requests=max_tree_requests,
    )


def test_build_repository_index_recursive_success() -> None:
    repo = FakeRepo()
    elements = [
        FakeGitTreeElement(path="src/main.py", element_type="blob", sha=SHA_BLOB),
        FakeGitTreeElement(path="docs/configuration.md", element_type="blob", sha=SHA_BLOB),
        FakeGitTreeElement(path="docs", element_type="tree", sha=SHA_SUBTREE),
    ]
    repo.tree_map[(SHA_TREE, True)] = FakeGitTree(tree=elements, truncated=False)

    index = build_repository_index(repo, SHA_TREE, make_settings())
    assert index.complete is True
    assert index.truncated_recursive is False
    assert index.incomplete_reasons == []
    assert len(index.entries) == 2

    paths = [e.path for e in index.entries]
    assert "docs/configuration.md" in paths
    assert "src/main.py" in paths

    # Confirm docs/configuration.md categorized as 'doc'
    doc_entry = next(e for e in index.entries if e.path == "docs/configuration.md")
    assert doc_entry.category == "doc"


def test_build_repository_index_truncated_fallback_success() -> None:
    repo = FakeRepo()
    # Root recursive call returns truncated=True
    repo.tree_map[(SHA_TREE, True)] = FakeGitTree(tree=[], truncated=True)

    # Non-recursive root walk
    root_elements = [
        FakeGitTreeElement(path="README.md", element_type="blob", sha=SHA_BLOB),
        FakeGitTreeElement(path="src", element_type="tree", sha=SHA_SUBTREE),
    ]
    repo.tree_map[(SHA_TREE, False)] = FakeGitTree(tree=root_elements, truncated=False)

    # Non-recursive subtree walk
    src_elements = [
        FakeGitTreeElement(path="app.py", element_type="blob", sha=SHA_BLOB),
    ]
    repo.tree_map[(SHA_SUBTREE, False)] = FakeGitTree(tree=src_elements, truncated=False)

    index = build_repository_index(repo, SHA_TREE, make_settings())
    assert index.complete is True
    assert index.truncated_recursive is True
    assert index.incomplete_reasons == []
    assert len(index.entries) == 2
    paths = {e.path for e in index.entries}
    assert paths == {"README.md", "src/app.py"}


def test_build_repository_index_request_budget_exhausted() -> None:
    repo = FakeRepo()
    repo.tree_map[(SHA_TREE, True)] = FakeGitTree(tree=[], truncated=True)

    # Set budget to 1 request. Initial recursive tree uses 1 request,
    # so non-recursive walk cannot proceed.
    settings = make_settings(max_tree_requests=1)
    index = build_repository_index(repo, SHA_TREE, settings)
    assert index.complete is False
    assert index.truncated_recursive is True
    assert any("limit reached" in r for r in index.incomplete_reasons)


def test_build_repository_index_subtree_failure_incomplete() -> None:
    repo = FakeRepo()
    repo.tree_map[(SHA_TREE, True)] = FakeGitTree(tree=[], truncated=True)

    # Root non-recursive returns a tree pointing to missing subtree
    root_elements = [
        FakeGitTreeElement(path="broken_sub", element_type="tree", sha=SHA_SUBTREE),
    ]
    repo.tree_map[(SHA_TREE, False)] = FakeGitTree(tree=root_elements, truncated=False)
    # Subtree 404/403 error
    repo.tree_map[(SHA_SUBTREE, False)] = UnknownObjectException(404, {"msg": "not found"}, {})

    index = build_repository_index(repo, SHA_TREE, make_settings())
    assert index.complete is False
    assert index.truncated_recursive is True
    assert any("Subtree fetch failed" in r for r in index.incomplete_reasons)
