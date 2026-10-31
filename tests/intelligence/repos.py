import hashlib
from collections.abc import Mapping

from docsentry.intelligence.repository.snapshot import RepoSnapshot


def make_repo(files: Mapping[str, str], commit_sha: str = "a" * 40) -> RepoSnapshot:
    paths = frozenset(files.keys())
    blob_shas = {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()[:40]
        for path, content in files.items()
    }
    return RepoSnapshot(
        commit_sha=commit_sha,
        files=dict(files),
        paths=paths,
        complete=True,
        incomplete_reasons=(),
        skipped=(),
        blob_shas=blob_shas,
        source_index_complete=True,
        source_scan_complete=True,
    )
