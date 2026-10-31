import asyncio
from typing import Any

from github import GithubException

from docsentry.github.checks import CheckRunPublisher, external_id, map_error
from docsentry.reporting.check_run import CheckAnnotation, CheckRunReport

H1, H2 = "a" * 40, "b" * 40


class FakeRun:
    def __init__(self, ext: str, sha: str, fail: GithubException | None = None) -> None:
        self.external_id, self.head_sha = ext, sha
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    def edit(self, **kw: Any) -> None:
        self.calls.append(kw)
        out = kw.get("output", {})
        if self.fail is not None and "annotations" in out:
            raise self.fail


class FakeCommit:
    def __init__(self, runs: list[FakeRun]) -> None:
        self.runs = runs

    def get_check_runs(self, check_name: str) -> list[FakeRun]:
        return self.runs


class FakeRepo:
    def __init__(self, existing: list[FakeRun] | None = None, create_exc: Exception | None = None):
        self.existing = existing or []
        self.created: list[dict[str, Any]] = []
        self.create_exc = create_exc
        self.writes: list[str] = []

    def get_commit(self, sha: str) -> FakeCommit:
        return FakeCommit([r for r in self.existing if r.head_sha == sha])

    def create_check_run(self, **kw: Any) -> FakeRun:
        if self.create_exc:
            raise self.create_exc
        self.created.append(kw)
        r = FakeRun(kw["external_id"], kw["head_sha"])
        self.existing.append(r)
        return r


class FakeClient:
    def __init__(self, repo: FakeRepo) -> None:
        self.repo = repo

    def get_repo(self, name: str) -> FakeRepo:
        return self.repo

    def __getattr__(self, name: str) -> Any:  # any other API use is a test failure
        raise AssertionError(f"forbidden GitHub call: {name}")


def report(n: int = 0) -> CheckRunReport:
    anns = tuple(
        CheckAnnotation(
            path="d.md",
            start_line=i + 1,
            end_line=i + 1,
            annotation_level="notice",
            title="t",
            message="m",
        )
        for i in range(n)
    )
    return CheckRunReport(title="t", summary="s", conclusion="neutral", annotations=anns)


def go(coro: Any) -> Any:
    return asyncio.run(coro)


def test_create_in_progress_on_exact_sha_with_external_id() -> None:
    repo = FakeRepo()
    pub = CheckRunPublisher("DocSentry")
    h, err = go(pub.begin(FakeClient(repo), "o", "r", 7, 3, H2))
    assert err is None and h is not None
    c = repo.created[0]
    assert c["head_sha"] == H2 and c["status"] == "in_progress" and c["name"] == "DocSentry"
    assert c["external_id"] == external_id(7, 3, H2)


def test_reuse_same_run_new_sha_new_run_old_untouched() -> None:
    repo = FakeRepo()
    pub = CheckRunPublisher("DocSentry")
    c = FakeClient(repo)
    h1, _ = go(pub.begin(c, "o", "r", 7, 3, H1))
    h1b, _ = go(pub.begin(c, "o", "r", 7, 3, H1))
    assert h1b.run is h1.run and len(repo.created) == 1
    h2, _ = go(pub.begin(c, "o", "r", 7, 3, H2))
    assert h2.run is not h1.run and len(repo.created) == 2
    go(pub.finish(h2, report(), 7, 3))
    assert h1.run.calls == []


def test_external_id_must_match() -> None:
    repo = FakeRepo([FakeRun("someone-elses", H1)])
    h, _ = go(CheckRunPublisher("DocSentry").begin(FakeClient(repo), "o", "r", 7, 3, H1))
    assert len(repo.created) == 1 and h is not None


def test_annotation_batches_of_50_no_duplicates_and_single_completion() -> None:
    repo = FakeRepo()
    pub = CheckRunPublisher("DocSentry")
    h, _ = go(pub.begin(FakeClient(repo), "o", "r", 7, 3, H1))
    out = go(pub.finish(h, report(120), 7, 3))
    calls = h.run.calls
    assert out.status == "published" and out.annotations_sent == 120
    assert [len(c["output"].get("annotations", [])) for c in calls] == [50, 50, 20]
    assert calls[0]["status"] == "completed" and all("status" not in c for c in calls[1:])
    lines = [a["start_line"] for c in calls for a in c["output"]["annotations"]]
    assert len(lines) == len(set(lines)) == 120


def test_bad_annotation_falls_back_to_summary_only() -> None:
    repo = FakeRepo()
    pub = CheckRunPublisher("DocSentry")
    h, _ = go(pub.begin(FakeClient(repo), "o", "r", 7, 3, H1))
    h.run.fail = GithubException(422, {}, {})
    out = go(pub.finish(h, report(3), 7, 3))
    assert out.status == "published" and out.annotations_dropped
    assert (
        "annotations" not in h.run.calls[-1]["output"]
        and h.run.calls[-1]["conclusion"] == "neutral"
    )


def test_failure_classes_map_to_safe_codes() -> None:
    assert map_error(GithubException(403, {}, {})) == "github_checks_permission_missing"
    assert map_error(GithubException(401, {}, {})) == "github_auth_failed"
    assert (
        map_error(GithubException(422, {}, {}), creating=True)
        == "github_check_unavailable_for_head"
    )
    assert map_error(GithubException(500, {}, {})) == "github_check_publish_failed"
    pub = CheckRunPublisher("DocSentry")
    h, out = go(
        pub.begin(
            FakeClient(FakeRepo(create_exc=GithubException(403, {"message": "secret"}, {}))),
            "o",
            "r",
            7,
            3,
            H1,
        )
    )
    assert h is None and out is not None and out.code == "github_checks_permission_missing"
    h, out = go(
        pub.begin(FakeClient(FakeRepo(create_exc=GithubException(422, {}, {}))), "o", "r", 7, 3, H1)
    )
    assert out is not None and out.status == "unavailable"


def test_finish_failure_is_contained() -> None:
    repo = FakeRepo()
    pub = CheckRunPublisher("DocSentry")
    h, _ = go(pub.begin(FakeClient(repo), "o", "r", 7, 3, H1))
    h.run.fail = GithubException(403, {}, {})
    out = go(pub.finish(h, report(2), 7, 3))
    assert out.status == "failed" and out.code == "github_checks_permission_missing"


def test_cancel_completes_only_own_run() -> None:
    repo = FakeRepo()
    pub = CheckRunPublisher("DocSentry")
    c = FakeClient(repo)
    h1, _ = go(pub.begin(c, "o", "r", 7, 3, H1))
    h2, _ = go(pub.begin(c, "o", "r", 7, 3, H2))
    go(pub.cancel(h1, 7, 3))
    assert h1.run.calls[-1]["conclusion"] == "cancelled" and h2.run.calls == []
