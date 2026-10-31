from collections.abc import Mapping
from dataclasses import dataclass

from docsentry.intelligence.models.common import SkippedAnalysisFile


@dataclass(frozen=True)
class RepoSnapshot:
    commit_sha: str
    files: Mapping[str, str]
    paths: frozenset[str]
    complete: bool
    incomplete_reasons: tuple[str, ...]
    skipped: tuple[SkippedAnalysisFile, ...]
    blob_shas: Mapping[str, str]
    source_index_complete: bool = True
    source_scan_complete: bool = True
