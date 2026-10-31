from collections.abc import Iterator
from typing import Any


class FakeCommit:
    def __init__(self, sha: str) -> None:
        self.sha = sha


class FakeRef:
    def __init__(self, ref: str, sha: str) -> None:
        self.ref = ref
        self.sha = sha


class FakeFile:
    def __init__(
        self,
        filename: str,
        status: str = "modified",
        additions: int = 1,
        deletions: int = 1,
        changes: int = 2,
        sha: str = "a" * 40,
        patch: str | None = "@@ -1 +1 @@\n-a\n+b",
        previous_filename: str | None = None,
    ) -> None:
        self.filename = filename
        self.status = status
        self.additions = additions
        self.deletions = deletions
        self.changes = changes
        self.sha = sha
        self.patch = patch
        self.previous_filename = previous_filename


class FakePaginatedList:
    def __init__(self, items: list[Any], page_size: int = 100) -> None:
        self._items = items
        self._page_size = page_size
        self.pages_requested = 0

    def __iter__(self) -> Iterator[Any]:
        for idx, item in enumerate(self._items):
            if idx % self._page_size == 0:
                self.pages_requested += 1
            yield item


class FakeComparison:
    def __init__(self, merge_base_sha: str | None) -> None:
        self.merge_base_commit = FakeCommit(merge_base_sha) if merge_base_sha else None


class FakePullRequest:
    def __init__(
        self,
        number: int = 1,
        title: str = "PR Title",
        html_url: str = "https://github.com/org/repo/pull/1",
        base_sha: str = "a" * 40,
        head_sha: str = "b" * 40,
        changed_files: int = 1,
        files: list[FakeFile] | None = None,
        draft: bool = False,
        state: str = "open",
    ) -> None:
        self.number = number
        self.title = title
        self.html_url = html_url
        self.base = FakeRef("main", base_sha)
        self.head = FakeRef("feature", head_sha)
        self.changed_files = changed_files
        self._files = files or [FakeFile("file1.py")]
        self.draft = draft
        self.state = state
        self.paginated_list = FakePaginatedList(self._files)

    def get_files(self) -> FakePaginatedList:
        return self.paginated_list


class FakeRepo:
    def __init__(
        self,
        repo_id: int = 123,
        name: str = "repo",
        owner: str = "org",
        pr: FakePullRequest | None = None,
        merge_base_sha: str | None = "a" * 40,
    ) -> None:
        self.id = repo_id
        self.name = name
        self.owner = owner
        self.pr = pr or FakePullRequest()
        self.merge_base_sha = merge_base_sha
        self.compare_calls: list[tuple[str, str]] = []
        self.contents_map: dict[tuple[str, str], Any] = {}
        self.contents_calls: list[tuple[str, str]] = []
        self.tree_map: dict[tuple[str, bool], Any] = {}
        self.tree_calls: list[tuple[str, bool]] = []

    def get_pull(self, number: int) -> FakePullRequest:
        return self.pr

    def compare(self, base: str, head: str) -> FakeComparison:
        self.compare_calls.append((base, head))
        return FakeComparison(self.merge_base_sha)

    def get_contents(self, path: str, ref: str = "") -> Any:
        self.contents_calls.append((path, ref))
        if (path, ref) in self.contents_map:
            val = self.contents_map[(path, ref)]
            if isinstance(val, Exception):
                raise val
            return val
        from github import UnknownObjectException

        raise UnknownObjectException(404, {"message": "Not Found"}, {})

    def get_git_tree(self, sha: str, recursive: bool = False) -> Any:
        self.tree_calls.append((sha, recursive))
        if (sha, recursive) in self.tree_map:
            val = self.tree_map[(sha, recursive)]
            if isinstance(val, Exception):
                raise val
            return val
        from github import UnknownObjectException

        raise UnknownObjectException(404, {"message": "Tree Not Found"}, {})


class FakeContentFile:
    def __init__(
        self,
        path: str,
        content: str | bytes | None = None,
        encoding: str = "base64",
        size: int = 10,
        sha: str = "c" * 40,
        file_type: str = "file",
    ) -> None:
        self.path = path
        self.content = content
        self.encoding = encoding
        self.size = size
        self.sha = sha
        self.type = file_type


class FakeGitTreeElement:
    def __init__(
        self,
        path: str,
        element_type: str = "blob",
        mode: str = "100644",
        sha: str = "d" * 40,
        size: int | None = 100,
    ) -> None:
        self.path = path
        self.type = element_type
        self.mode = mode
        self.sha = sha
        self.size = size


class FakeGitTree:
    def __init__(
        self,
        tree: list[FakeGitTreeElement],
        truncated: bool = False,
        sha: str = "e" * 40,
    ) -> None:
        self.tree = tree
        self.truncated = truncated
        self.sha = sha


class FakeGithub:
    def __init__(self, repo: FakeRepo | None = None) -> None:
        self._repo = repo or FakeRepo()

    def get_repo(self, full_name_or_id: str | int) -> FakeRepo:
        return self._repo


class FakeIntegration:
    def __init__(self, client: FakeGithub | None = None) -> None:
        self.client = client or FakeGithub()
        self.calls: list[int] = []

    def get_github_for_installation(self, installation_id: int, **kwargs: Any) -> FakeGithub:
        self.calls.append(installation_id)
        return self.client
