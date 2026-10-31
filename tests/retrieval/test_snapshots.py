import base64

import pytest
from github import RateLimitExceededException

from docsentry.config import Settings
from docsentry.retrieval.errors import RateLimited
from docsentry.retrieval.models import ChangedFile
from docsentry.retrieval.snapshots import (
    GitHubFileReader,
    build_snapshots,
    plan_snapshots,
    read_file_at_sha,
)
from tests.retrieval.fakes import FakeContentFile, FakeRepo

SHA_BASE = "a" * 40
SHA_HEAD = "b" * 40


def make_settings(
    max_file_bytes: int = 1000,
    max_snapshot_files: int = 10,
    max_total_snapshot_bytes: int = 5000,
) -> Settings:
    return Settings(
        github_app_id="123",
        github_private_key="key",
        github_webhook_secret="sec",
        max_file_bytes=max_file_bytes,
        max_snapshot_files=max_snapshot_files,
        max_total_snapshot_bytes=max_total_snapshot_bytes,
    )


def test_read_file_at_sha_utf8_and_ref_recorded() -> None:
    repo = FakeRepo()
    utf8_text = "Hello world! 🚀 Ça va?"
    encoded = base64.b64encode(utf8_text.encode("utf-8")).decode("ascii")
    repo.contents_map[("docs/hello.md", SHA_HEAD)] = FakeContentFile(
        path="docs/hello.md",
        content=encoded,
        size=len(utf8_text.encode("utf-8")),
    )

    res = read_file_at_sha(repo, "docs/hello.md", SHA_HEAD, make_settings())
    assert res.missing is False
    assert res.skipped is None
    assert res.version is not None
    assert res.version.text == utf8_text
    assert res.version.commit_sha == SHA_HEAD
    assert ("docs/hello.md", SHA_HEAD) in repo.contents_calls


def test_read_file_at_sha_binary_and_not_utf8() -> None:
    repo = FakeRepo()
    # Binary with NUL
    bin_bytes = b"some text with \x00 in it"
    repo.contents_map[("bin.dat", SHA_HEAD)] = FakeContentFile(
        path="bin.dat",
        content=base64.b64encode(bin_bytes).decode("ascii"),
        size=len(bin_bytes),
    )
    res_bin = read_file_at_sha(repo, "bin.dat", SHA_HEAD, make_settings())
    assert res_bin.skipped is not None
    assert res_bin.skipped.reason == "binary"

    # Invalid UTF-8
    invalid_bytes = b"invalid \xff\xfe utf8"
    repo.contents_map[("invalid.txt", SHA_HEAD)] = FakeContentFile(
        path="invalid.txt",
        content=base64.b64encode(invalid_bytes).decode("ascii"),
        size=len(invalid_bytes),
    )
    res_invalid = read_file_at_sha(repo, "invalid.txt", SHA_HEAD, make_settings())
    assert res_invalid.skipped is not None
    assert res_invalid.skipped.reason == "not_utf8"


def test_read_file_at_sha_oversized_and_empty_big_file() -> None:
    repo = FakeRepo()
    settings = make_settings(max_file_bytes=50)

    # Size attribute exceeds limit
    repo.contents_map[("large.py", SHA_HEAD)] = FakeContentFile(
        path="large.py",
        size=100,
    )
    res_large = read_file_at_sha(repo, "large.py", SHA_HEAD, settings)
    assert res_large.skipped is not None
    assert res_large.skipped.reason == "oversized"

    # Big file with empty content returned by GitHub API
    repo.contents_map[("large_empty.py", SHA_HEAD)] = FakeContentFile(
        path="large_empty.py",
        content="",
        size=2000,
    )
    res_empty = read_file_at_sha(repo, "large_empty.py", SHA_HEAD, settings)
    assert res_empty.skipped is not None
    assert res_empty.skipped.reason == "oversized"


def test_read_file_at_sha_directory_and_submodule() -> None:
    repo = FakeRepo()
    repo.contents_map[("mydir", SHA_HEAD)] = [FakeContentFile(path="mydir/a.txt")]
    res_dir = read_file_at_sha(repo, "mydir", SHA_HEAD, make_settings())
    assert res_dir.skipped is not None
    assert res_dir.skipped.reason == "directory"

    repo.contents_map[("mysubmodule", SHA_HEAD)] = FakeContentFile(
        path="mysubmodule",
        file_type="submodule",
    )
    res_sub = read_file_at_sha(repo, "mysubmodule", SHA_HEAD, make_settings())
    assert res_sub.skipped is not None
    assert res_sub.skipped.reason == "submodule"


def test_reader_cache() -> None:
    repo = FakeRepo()
    content = base64.b64encode(b"content").decode("ascii")
    repo.contents_map[("file.py", SHA_HEAD)] = FakeContentFile(
        path="file.py", content=content, size=7
    )

    reader = GitHubFileReader(repo, make_settings())
    res1 = reader.read("file.py", SHA_HEAD)
    res2 = reader.read("file.py", SHA_HEAD)

    assert res1 is res2
    assert len(repo.contents_calls) == 1


def test_plan_snapshots_prioritization_and_caps() -> None:
    changed = [
        ChangedFile(
            filename="image.png",
            status="added",
            additions=1,
            deletions=0,
            changes=1,
            blob_sha=SHA_HEAD,
            category="other",
        ),
        ChangedFile(
            filename="config.yaml",
            status="modified",
            additions=1,
            deletions=0,
            changes=1,
            blob_sha=SHA_HEAD,
            category="config",
        ),
        ChangedFile(
            filename="main.py",
            status="modified",
            additions=1,
            deletions=0,
            changes=1,
            blob_sha=SHA_HEAD,
            category="source",
        ),
        ChangedFile(
            filename="docs/readme.md",
            status="modified",
            additions=1,
            deletions=0,
            changes=1,
            blob_sha=SHA_HEAD,
            category="doc",
        ),
    ]

    # Cap at 2: doc and source should be selected, config excess over_budget, other unsupported
    settings = make_settings(max_snapshot_files=2)
    planned, skipped = plan_snapshots(changed, settings)

    assert [f.filename for f in planned] == ["docs/readme.md", "main.py"]
    assert {s.path: s.reason for s in skipped} == {
        "image.png": "unsupported_type",
        "config.yaml": "over_budget",
    }


def test_build_snapshots_mappings_and_budget() -> None:
    repo = FakeRepo()
    b64_a = base64.b64encode(b"content_a").decode("ascii")
    b64_b = base64.b64encode(b"content_b").decode("ascii")

    # added
    repo.contents_map[("added.py", SHA_HEAD)] = FakeContentFile(
        path="added.py", content=b64_b, size=9
    )
    # removed
    repo.contents_map[("removed.py", SHA_BASE)] = FakeContentFile(
        path="removed.py", content=b64_a, size=9
    )
    # renamed
    repo.contents_map[("old_name.py", SHA_BASE)] = FakeContentFile(
        path="old_name.py", content=b64_a, size=9
    )
    repo.contents_map[("new_name.py", SHA_HEAD)] = FakeContentFile(
        path="new_name.py", content=b64_b, size=9
    )

    planned = [
        ChangedFile(
            filename="added.py",
            status="added",
            additions=1,
            deletions=0,
            changes=1,
            blob_sha=SHA_HEAD,
            category="source",
        ),
        ChangedFile(
            filename="removed.py",
            status="removed",
            additions=0,
            deletions=1,
            changes=1,
            blob_sha=SHA_BASE,
            category="source",
        ),
        ChangedFile(
            filename="new_name.py",
            previous_filename="old_name.py",
            status="renamed",
            additions=0,
            deletions=0,
            changes=0,
            blob_sha=SHA_HEAD,
            category="source",
        ),
    ]

    res = build_snapshots(repo, planned, SHA_BASE, SHA_HEAD, make_settings())
    assert len(res.snapshots) == 3
    assert res.errors == []
    assert res.skipped == []

    # Verify refs in get_contents calls
    calls = repo.contents_calls
    assert ("added.py", SHA_HEAD) in calls
    assert ("removed.py", SHA_BASE) in calls
    assert ("old_name.py", SHA_BASE) in calls
    assert ("new_name.py", SHA_HEAD) in calls


def test_build_snapshots_rate_limit_propagates() -> None:
    repo = FakeRepo()
    repo.contents_map[("file.py", SHA_HEAD)] = RateLimitExceededException(
        403, None, headers={"x-ratelimit-remaining": "0"}
    )

    planned = [
        ChangedFile(
            filename="file.py",
            status="added",
            additions=1,
            deletions=0,
            changes=1,
            blob_sha=SHA_HEAD,
            category="source",
        )
    ]
    with pytest.raises(RateLimited):
        build_snapshots(repo, planned, SHA_BASE, SHA_HEAD, make_settings())
