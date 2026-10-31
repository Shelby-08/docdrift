import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from docsentry.cli import main
from docsentry.replay.evaluate import (
    Case,
    Manifest,
    aggregate,
    evaluate,
    evaluate_case,
    to_markdown,
)
from docsentry.replay.git_source import Git, GitError, validate_rev
from docsentry.replay.runner import analyze_local

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(repo: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo), *args]
    out = subprocess.run(cmd, capture_output=True, text=True, env=ENV, check=True)
    return out.stdout.strip()


def commit(repo: Path, files: dict[str, str | None], msg: str) -> str:
    for p, t in files.items():
        f = repo / p
        if t is None:
            f.unlink()
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(t, encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-q")
    return r


DOC30 = "# Configuration\n\nThe default timeout is 30 seconds.\n"


def default_history(r: Path) -> tuple[str, str, str]:
    files = {"src/config.py": "DEFAULT_TIMEOUT = 30\n", "docs/configuration.md": DOC30}
    c0 = commit(r, files, "init")
    c1 = commit(r, {"src/config.py": "DEFAULT_TIMEOUT = 60\n"}, "code")
    c2 = commit(r, {"docs/configuration.md": DOC30.replace("30", "60")}, "docs fix")
    return c0, c1, c2


def drift_case(repo: Path, c0: str, c1: str, c2: str, cid: str = "d") -> Case:
    return Case(
        id=cid,
        kind="drift",
        repo_path=str(repo),
        base=c0,
        code_commit=c1,
        doc_fix_commit=c2,
    )


def test_changed_default_exact_lines_and_evaluate_hits(repo: Path) -> None:
    c0, c1, c2 = default_history(repo)
    res = analyze_local(str(repo), c0, c1)
    f = [x for x in res.findings if x.temporal_status.value == "newly_introduced"]
    assert len(f) == 1
    assert (f[0].documentation_file, f[0].documentation_line) == ("docs/configuration.md", 3)
    assert (f[0].code_file, f[0].code_line) == ("src/config.py", 1)
    row = evaluate_case(drift_case(repo, c0, c1, c2))
    assert row["findings"] == 1 and row["path_hit"] is True and row["line_hit"] is True
    assert row["line_match"] == "computed" and row["error"] is None


CATEGORIES = [
    (
        "renamed_flag",
        {"src/config.py": "ENABLE_CACHE = True\n"},
        {"src/config.py": "USE_CACHE = True\n"},
        "# Config\n\nSet `ENABLE_CACHE` to turn on caching.\n",
        "R3",
    ),
    (
        "param_removed",
        {"src/api.py": "def fetch(url, retries=3):\n    return url\n"},
        {"src/api.py": "def fetch(url, attempts=3):\n    return url\n"},
        "# API\n\nUse `fetch(url, retries)` to download.\n",
        "R2",
    ),
    (
        "removed_feature",
        {"src/api.py": "def legacy_sync(x):\n    return x\n"},
        {"src/api.py": "def other(x):\n    return x\n"},
        "# API\n\nUse `legacy_sync` to synchronise data.\n",
        "R4",
    ),
    (
        "param_default",
        {"src/api.py": "def fetch(url, retries=3):\n    return url\n"},
        {"src/api.py": "def fetch(url, retries=5):\n    return url\n"},
        "# API\n\n`retries` defaults to 3.\n",
        "R1",
    ),
]


@pytest.mark.parametrize(("name", "base", "head", "doc", "rule"), CATEGORIES)
def test_problem05_category_fixtures(
    repo: Path, name: str, base: dict[str, str], head: dict[str, str], doc: str, rule: str
) -> None:
    c0 = commit(repo, {**base, "docs/d.md": doc}, "init")
    c1 = commit(repo, head, "code")
    fixed = doc.replace("ENABLE_CACHE", "USE_CACHE").replace("legacy_sync", "other")
    fixed = fixed.replace("retries", "attempts").replace("3", "5")
    c2 = commit(repo, {"docs/d.md": fixed}, "fix docs")
    row = evaluate_case(drift_case(repo, c0, c1, c2, name))
    assert row["error"] is None and row["findings"] == 1 and row["path_hit"] is True, name
    res = analyze_local(str(repo), c0, c1)
    assert [f.rule_id for f in res.findings] == [rule]


def test_controls_have_zero_findings(repo: Path) -> None:
    base = {"src/a.py": "A = 1\n", "src/b.py": "def f():\n    return 1\n", "docs/x.md": "Hello.\n"}
    c0 = commit(repo, base, "init")
    c_docs = commit(repo, {"docs/x.md": "Hello there.\n"}, "docs only")
    c_code = commit(repo, {"src/b.py": "def f():\n    return 2\n"}, "unrelated")
    same = {
        "src/config.py": "DEFAULT_TIMEOUT = 60\n",
        "docs/c.md": "The default timeout is 60 seconds.\n",
    }
    c_same = commit(repo, same, "same pr")
    cases = [
        Case(id="docs_only", kind="control", repo_path=str(repo), base=c0, code_commit=c_docs),
        Case(id="unrelated", kind="control", repo_path=str(repo), base=c_docs, code_commit=c_code),
        Case(id="same_pr", kind="control", repo_path=str(repo), base=c_code, code_commit=c_same),
    ]
    rep = evaluate(Manifest(cases=cases))
    assert rep["aggregates"]["findings_per_control_case"] == [0, 0, 0]
    assert rep["aggregates"]["errors"] == 0


def test_doc_corrected_in_same_commit_no_new_drift(repo: Path) -> None:
    c0 = commit(repo, {"src/config.py": "DEFAULT_TIMEOUT = 30\n", "docs/c.md": DOC30}, "init")
    both = {"src/config.py": "DEFAULT_TIMEOUT = 60\n", "docs/c.md": DOC30.replace("30", "60")}
    c1 = commit(repo, both, "both")
    assert analyze_local(str(repo), c0, c1).findings == ()


def test_renamed_doc_file_with_code_change(repo: Path) -> None:
    c0 = commit(repo, {"src/config.py": "DEFAULT_TIMEOUT = 30\n", "docs/old.md": DOC30}, "init")
    git(repo, "mv", "docs/old.md", "docs/new.md")
    c1 = commit(repo, {"src/config.py": "DEFAULT_TIMEOUT = 60\n"}, "rename+code")
    res = analyze_local(str(repo), c0, c1)
    assert [f.documentation_file for f in res.findings] == ["docs/new.md"]


def test_oversized_and_binary_files_are_skipped_not_fatal(repo: Path) -> None:
    c0 = commit(repo, {"src/config.py": "DEFAULT_TIMEOUT = 30\n", "docs/c.md": DOC30}, "init")
    (repo / "data.bin").write_bytes(b"\x00\x01\x02" * 100)
    c1 = commit(repo, {"src/config.py": "DEFAULT_TIMEOUT = 60\n"}, "code")
    res = analyze_local(str(repo), c0, c1, max_file_bytes=10)
    assert any(s.reason == "oversized" for s in res.skipped_files) and res.complete is False


def test_no_write_or_network_git_commands_and_no_sockets(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c0, c1, _ = default_history(repo)

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("network")

    monkeypatch.setattr(socket, "socket", boom)
    g = Git(str(repo))
    analyze_local(str(repo), c0, c1, git=g)
    used = {c[0] for c in g.issued}
    assert used <= {"rev-parse", "merge-base", "diff", "cat-file", "ls-tree"}
    assert not any(a in used for a in ("fetch", "pull", "checkout", "push", "clone", "reset"))
    with pytest.raises(GitError):
        g.run("fetch")


@pytest.mark.parametrize(
    "bad",
    [
        "--upload-pack=evil",
        "-x",
        "a;b",
        "a b",
        "$(id)",
        "a`id`",
        "a..b",
        "",
        "a|b",
        "x\ny",
        "--help",
    ],
)
def test_revision_injection_rejected(bad: str, repo: Path) -> None:
    default_history(repo)
    with pytest.raises(GitError):
        validate_rev(bad)
    with pytest.raises(GitError):
        Git(str(repo)).resolve(bad)


def test_bad_repo_and_missing_commit(repo: Path) -> None:
    with pytest.raises(GitError):
        Git("--upload-pack=x")
    with pytest.raises(GitError):
        Git(str(repo / "nope"))
    c0, _, _ = default_history(repo)
    case = Case(id="m", kind="control", repo_path=str(repo), base=c0, code_commit="deadbeef" * 5)
    row = evaluate_case(case)
    assert row["error"] is not None and row["findings"] == 0


def _row(i: str, kind: str, n: int, ph: bool | None, lh: bool | None, lm: str) -> dict[str, object]:
    return {
        "id": i,
        "kind": kind,
        "findings": n,
        "categories": [],
        "path_hit": ph,
        "line_hit": lh,
        "line_match": lm,
        "error": None,
    }


def test_aggregate_math() -> None:
    rows = [
        _row("a", "drift", 2, True, True, "computed"),
        _row("b", "drift", 0, False, None, "unavailable"),
        _row("c", "drift", 1, True, False, "computed"),
        _row("d", "control", 3, None, None, "not_applicable"),
    ]
    a = aggregate(rows)  # type: ignore[arg-type]
    assert a["path_recall"] == pytest.approx(2 / 3) and a["line_recall"] == 0.5
    assert a["line_computable_cases"] == 2 and a["median_findings_per_case"] == 1.5
    assert a["max_findings_per_case"] == 3 and a["findings_per_control_case"] == [3]
    assert aggregate([])["path_recall"] is None


def test_cli_replay_and_evaluate_deterministic(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    c0, c1, c2 = default_history(repo)
    assert main(["replay", "--repo", str(repo), "--base", c0, "--head", c1]) == 0
    md = capsys.readouterr().out
    assert "newly introduced" in md and "docs/configuration.md" in md
    args = ["replay", "--repo", str(repo), "--base", c0, "--head", c1, "--format", "json"]
    assert main(args) == 0
    j1 = capsys.readouterr().out
    main(args)
    assert capsys.readouterr().out == j1
    assert json.loads(j1)["report"]["conclusion"] == "neutral"
    man = tmp_path / "m.json"
    case = {
        "id": "d",
        "kind": "drift",
        "repo_path": str(repo),
        "base": c0,
        "code_commit": c1,
        "doc_fix_commit": c2,
    }
    man.write_text(json.dumps([case]))
    assert main(["evaluate", "--manifest", str(man)]) == 0
    out = capsys.readouterr().out
    assert "Path recall: 100%" in out and "| d | drift | 1 |" in out
    expected = to_markdown(evaluate(Manifest(cases=[drift_case(repo, c0, c1, c2)])))
    assert expected == out.rstrip("\n")
    assert main(["replay", "--repo", str(repo), "--base=--evil", "--head", c1]) == 2
