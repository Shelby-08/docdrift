"""Read-only local git source: builds a Stage 2 style bundle from two commits. No network."""

import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

from docsentry.retrieval.classify import classify_path
from docsentry.retrieval.models import (
    ChangedFile,
    FileVersion,
    PullRequestBundle,
    PullRequestContext,
    RepositoryFileEntry,
    RepositoryFileIndex,
    SkippedFile,
)
from docsentry.retrieval.snapshots import FileReadResult

ALLOWED = frozenset({"rev-parse", "merge-base", "diff", "cat-file", "ls-tree"})
REV_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/~^@{}-]{0,199}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
TIMEOUT = 30
MAX_OUTPUT = 50_000_000


class GitError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def validate_rev(rev: str) -> str:
    if not REV_RE.match(rev) or ".." in rev or rev.endswith(".lock"):
        raise GitError("invalid_revision")
    return rev


class Git:
    """Fixed-argv, shell-free, read-only git runner."""

    def __init__(self, repo: str) -> None:
        if repo.startswith("-") or not os.path.isdir(repo):
            raise GitError("invalid_repo")
        self._repo = repo
        self._env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_PAGER": "cat",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        self.issued: list[tuple[str, ...]] = []

    def run(self, *args: str) -> bytes:
        if not args or args[0] not in ALLOWED:
            raise GitError("git_command_not_allowed")
        argv = ["git", "--no-pager", "-C", self._repo, *args]
        self.issued.append(tuple(args))
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, shell=False
                argv, capture_output=True, timeout=TIMEOUT, env=self._env, shell=False, check=False
            )
        except subprocess.TimeoutExpired:
            raise GitError("git_timeout") from None
        except OSError:
            raise GitError("git_unavailable") from None
        if proc.returncode != 0 or len(proc.stdout) > MAX_OUTPUT:
            raise GitError("git_failed")
        return proc.stdout

    def resolve(self, rev: str) -> str:
        out = self.run("rev-parse", "--verify", "--end-of-options", validate_rev(rev) + "^{commit}")
        sha = out.decode("ascii", "replace").strip()
        if not SHA_RE.match(sha):
            raise GitError("revision_not_found")
        return sha

    def merge_base(self, a: str, b: str) -> str | None:
        try:
            sha = self.run("merge-base", a, b).decode("ascii", "replace").strip()
        except GitError:
            return None
        return sha if SHA_RE.match(sha) else None

    def blob_sha(self, sha: str, path: str) -> str | None:
        try:
            out = self.run("rev-parse", "--verify", "--end-of-options", f"{sha}:{path}")
        except GitError:
            return None
        s = out.decode("ascii", "replace").strip()
        return s if SHA_RE.match(s) else None


class GitFileSource:
    def __init__(self, git: Git, max_file_bytes: int = 1_000_000) -> None:
        self._git = git
        self._max = max_file_bytes

    def read(self, path: str, sha: str) -> FileReadResult:
        spec = f"{sha}:{path}"
        try:
            size = int(self._git.run("cat-file", "-s", spec).strip())
        except (GitError, ValueError):
            return FileReadResult(missing=True)
        if size > self._max:
            sk = SkippedFile(path=path, commit_sha=sha, reason="oversized", detail=f"{size} bytes")
            return FileReadResult(skipped=sk)
        try:
            data = self._git.run("cat-file", "blob", spec)
        except GitError:
            return FileReadResult(missing=True)
        if b"\0" in data[:8000]:
            return FileReadResult(
                skipped=SkippedFile(path=path, commit_sha=sha, reason="binary", detail="")
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return FileReadResult(
                skipped=SkippedFile(path=path, commit_sha=sha, reason="not_utf8", detail="")
            )
        blob = self._git.blob_sha(sha, path) or ""
        return FileReadResult(
            version=FileVersion(path=path, commit_sha=sha, blob_sha=blob, size=size, text=text)
        )


def _index(git: Git, sha: str) -> RepositoryFileIndex:
    out = git.run("ls-tree", "-r", "-z", "--long", sha)
    entries: list[RepositoryFileEntry] = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, raw_path = rec.partition(b"\t")
        parts = meta.decode("ascii", "replace").split()
        if len(parts) < 4 or parts[1] != "blob":
            continue
        path = raw_path.decode("utf-8", "replace")
        size = int(parts[3]) if parts[3].isdigit() else 0
        entries.append(
            RepositoryFileEntry(
                path=path,
                type="blob",
                mode=parts[0],
                blob_sha=parts[2],
                size=size,
                commit_sha=sha,
                category=classify_path(path),
            )
        )
    return RepositoryFileIndex(commit_sha=sha, entries=entries, complete=True)


_STATUS = {"A": "added", "M": "modified", "D": "removed", "R": "renamed"}


def _changed(git: Git, base: str, head: str, head_blobs: dict[str, str]) -> list[ChangedFile]:
    out = git.run("diff", "--name-status", "-M", "-z", "--no-ext-diff", base, head)
    toks = [t.decode("utf-8", "replace") for t in out.split(b"\0") if t]
    changed: list[ChangedFile] = []
    i = 0
    while i < len(toks):
        code = toks[i][0]
        if code in ("R", "C") and i + 2 < len(toks):
            prev, name, i = toks[i + 1], toks[i + 2], i + 3
        elif i + 1 < len(toks):
            prev, name, i = None, toks[i + 1], i + 2
        else:
            break
        status = _STATUS.get(code, "modified") if code != "C" else "added"
        changed.append(
            ChangedFile(
                filename=name,
                previous_filename=prev if code == "R" else None,
                status=status,
                additions=0,
                deletions=0,
                changes=0,
                blob_sha=head_blobs.get(name, ""),
                category=classify_path(name),
            )
        )
    return changed


def build_local_bundle(
    git: Git, base_rev: str, head_rev: str, name: str = "local"
) -> PullRequestBundle:
    base_sha, head_sha = git.resolve(base_rev), git.resolve(head_rev)
    mb = git.merge_base(base_sha, head_sha)
    base_index = _index(git, mb or base_sha)
    head_index = _index(git, head_sha)
    heads = {e.path: e.blob_sha for e in head_index.entries}
    ctx = PullRequestContext(
        delivery_id="local_git",  # source marker: no GitHub fields exist for local replays
        installation_id=1,  # sentinel: no GitHub installation
        owner="local_git",
        repository=name,
        repository_id=1,  # sentinel
        pull_number=1,  # sentinel
        title="",
        html_url="https://local.invalid/",
        base_ref="local",
        head_ref="local",
        base_sha=base_sha,
        head_sha=head_sha,
        merge_base_sha=mb,
        state="open",
        is_draft=False,
        event_head_sha=head_sha,
    )
    changed = _changed(git, mb or base_sha, head_sha, heads)
    return PullRequestBundle(
        context=ctx,
        changed_files=changed,
        changed_files_complete=True,
        reported_changed_files=len(changed),
        snapshots=[],
        skipped_files=[],
        base_index=base_index,
        head_index=head_index,
        errors=[],
        warnings=[],
        retrieved_at="1970-01-01T00:00:00Z",
    )


def repo_name(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(path).resolve().name)[:80] or "repo"


def changed_doc_lines(git: Git, fix_sha: str) -> dict[str, list[tuple[int, int]]]:
    """Old-side line ranges changed by the fix commit, for .md/.markdown files only."""
    out = git.run("diff", "-U0", "--no-ext-diff", "--no-color", "-M", f"{fix_sha}^", fix_sha)
    ranges: dict[str, list[tuple[int, int]]] = {}
    old = new = ""
    for raw in out.decode("utf-8", "replace").splitlines():
        if raw.startswith("--- "):
            old = raw[4:].removeprefix("a/") if raw[4:] != "/dev/null" else ""
        elif raw.startswith("+++ "):
            new = raw[4:].removeprefix("b/") if raw[4:] != "/dev/null" else ""
            for p in (old, new):
                if p.lower().endswith((".md", ".markdown")):
                    ranges.setdefault(p, [])
        elif raw.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", raw)
            path = old or new
            if m and path.lower().endswith((".md", ".markdown")):
                start, cnt = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
                if cnt > 0:
                    ranges.setdefault(path, []).append((start, start + cnt - 1))
                if new and new != old:
                    ranges.setdefault(new, [])
    return ranges


def rev_list_args_ok(revs: Sequence[str]) -> bool:
    return all(REV_RE.match(r) for r in revs)
