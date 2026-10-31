import inspect

import github
import github.Auth
from github.ContentFile import ContentFile
from github.File import File
from github.GitTree import GitTree
from github.GitTreeElement import GitTreeElement
from github.PullRequest import PullRequest
from github.Repository import Repository
from urllib3.util import Retry


def test_auth_and_integration_contract():
    assert hasattr(github.Auth, "AppAuth")
    app_auth_params = inspect.signature(github.Auth.AppAuth).parameters
    assert "app_id" in app_auth_params
    assert "private_key" in app_auth_params

    assert hasattr(github.Auth, "AppInstallationAuth")
    inst_auth_params = inspect.signature(github.Auth.AppInstallationAuth).parameters
    assert "app_auth" in inst_auth_params
    assert "installation_id" in inst_auth_params

    assert hasattr(github, "GithubIntegration")
    assert hasattr(github.GithubIntegration, "get_github_for_installation")


def test_github_client_contract():
    gh_params = inspect.signature(github.Github).parameters
    assert "timeout" in gh_params
    assert "per_page" in gh_params
    assert "retry" in gh_params

    # Verify explicit Retry passing
    app_auth = github.Auth.AppAuth("123", "fake-key")
    inst_auth = github.Auth.AppInstallationAuth(app_auth, 456)
    client = github.Github(
        auth=inst_auth,
        timeout=15,
        per_page=100,
        retry=Retry(total=0, connect=0, read=0, status=0),
    )
    assert client is not None


def test_repository_contract():
    assert hasattr(github.Github, "get_repo")
    get_repo_params = inspect.signature(github.Github.get_repo).parameters
    assert "full_name_or_id" in get_repo_params

    get_pull_params = inspect.signature(Repository.get_pull).parameters
    assert "number" in get_pull_params

    compare_params = inspect.signature(Repository.compare).parameters
    assert "base" in compare_params
    assert "head" in compare_params

    get_contents_params = inspect.signature(Repository.get_contents).parameters
    assert "path" in get_contents_params
    assert "ref" in get_contents_params

    get_git_tree_params = inspect.signature(Repository.get_git_tree).parameters
    assert "sha" in get_git_tree_params
    assert "recursive" in get_git_tree_params


def test_pull_request_and_file_contract():
    pr_attrs = [
        "number",
        "title",
        "html_url",
        "state",
        "draft",
        "changed_files",
        "base",
        "head",
        "get_files",
    ]
    for attr in pr_attrs:
        assert hasattr(PullRequest, attr)

    file_attrs = [
        "filename",
        "previous_filename",
        "status",
        "additions",
        "deletions",
        "changes",
        "sha",
        "patch",
        "raw_url",
    ]
    for attr in file_attrs:
        assert hasattr(File, attr)


def test_content_file_and_tree_contract():
    for attr in ["size", "sha", "type", "encoding", "content", "decoded_content"]:
        assert hasattr(ContentFile, attr)

    for attr in ["truncated", "tree", "sha", "raw_data"]:
        assert hasattr(GitTree, attr)

    for attr in ["path", "mode", "type", "size", "sha"]:
        assert hasattr(GitTreeElement, attr)


def test_exceptions_contract():
    for exc_cls in [
        github.GithubException,
        github.BadCredentialsException,
        github.UnknownObjectException,
        github.RateLimitExceededException,
    ]:
        assert issubclass(exc_cls, Exception)
        init_params = inspect.signature(exc_cls.__init__).parameters
        assert "status" in init_params
        assert "data" in init_params
        assert "headers" in init_params
