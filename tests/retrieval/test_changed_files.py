import pytest
from github import GithubException

from docsentry.retrieval.changed_files import list_changed_files
from docsentry.retrieval.errors import PermissionDenied
from tests.retrieval.fakes import FakeFile, FakePullRequest


def test_changed_files_pagination_and_complete() -> None:
    files = [FakeFile(f"file_{i}.py") for i in range(250)]
    pr = FakePullRequest(changed_files=250, files=files)

    res = list_changed_files(pr)
    assert len(res.files) == 250
    assert res.complete is True
    assert res.reported_total == 250
    assert pr.paginated_list.pages_requested == 3


def test_changed_files_exactly_3000() -> None:
    files = [FakeFile(f"file_{i}.py") for i in range(3000)]
    pr = FakePullRequest(changed_files=3000, files=files)

    res = list_changed_files(pr, hard_cap=3000)
    assert len(res.files) == 3000
    assert res.complete is True


def test_changed_files_over_hard_cap_incomplete() -> None:
    files = [FakeFile(f"file_{i}.py") for i in range(3000)]
    pr = FakePullRequest(changed_files=3500, files=files)

    res = list_changed_files(pr, hard_cap=3000)
    assert res.complete is False
    assert res.reported_total == 3500


def test_changed_files_fewer_than_reported_incomplete() -> None:
    files = [FakeFile("file1.py")]
    pr = FakePullRequest(changed_files=5, files=files)

    res = list_changed_files(pr)
    assert res.complete is False
    assert len(res.files) == 1


def test_changed_files_statuses_and_renames() -> None:
    files = [
        FakeFile("new.py", status="added", patch="@@ -0,0 +1 @@\n+val = 1"),
        FakeFile(
            "renamed.py",
            status="renamed",
            previous_filename="old.py",
            patch=None,
        ),
        FakeFile("deleted.py", status="removed"),
    ]
    pr = FakePullRequest(changed_files=3, files=files)

    res = list_changed_files(pr)
    assert res.complete is True
    assert res.files[0].status == "added"
    assert res.files[0].category == "source"
    assert res.files[1].previous_filename == "old.py"
    assert res.files[1].patch is None


def test_changed_files_api_error_raises() -> None:
    class FailingPR:
        changed_files = 1

        def get_files(self) -> None:
            raise GithubException(403, {"message": "Forbidden"})

    with pytest.raises(PermissionDenied):
        list_changed_files(FailingPR())
