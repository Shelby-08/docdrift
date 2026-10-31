from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from docsentry.retrieval.models import PullRequestBundle

JobStatus = Literal["queued", "running", "succeeded", "failed", "superseded", "duplicate"]


@dataclass(frozen=True)
class JobRecord:
    status: JobStatus
    delivery_id: str
    repo_id: int
    pr_number: int
    event_head_sha: str
    bundle_head_sha: str | None
    seq: int
    attempts: int
    error_code: str | None = None
    finished_at: str | None = None


class BundleStore:
    """Bounded store for latest PR bundles, records, sequence numbers, and processed heads."""

    def __init__(self, capacity: int = 10) -> None:
        self._capacity = capacity
        self._seqs: dict[tuple[int, int], int] = {}
        self._records: dict[tuple[int, int], JobRecord] = {}
        self._bundles: OrderedDict[tuple[int, int], PullRequestBundle] = OrderedDict()
        self._succeeded_heads: set[tuple[int, int, str]] = set()

    def next_seq(self, key: tuple[int, int]) -> int:
        current = self._seqs.get(key, 0) + 1
        self._seqs[key] = current
        return current

    def latest_seq(self, key: tuple[int, int]) -> int:
        return self._seqs.get(key, 0)

    def get_record(self, key: tuple[int, int]) -> JobRecord | None:
        return self._records.get(key)

    def get_bundle(self, key: tuple[int, int]) -> PullRequestBundle | None:
        return self._bundles.get(key)

    def has_succeeded_head(self, repo_id: int, pr_number: int, head_sha: str) -> bool:
        return (repo_id, pr_number, head_sha.lower()) in self._succeeded_heads

    def record_succeeded_head(self, repo_id: int, pr_number: int, head_sha: str) -> None:
        self._succeeded_heads.add((repo_id, pr_number, head_sha.lower()))

    def commit_result(
        self,
        key: tuple[int, int],
        seq: int,
        record: JobRecord,
        bundle: PullRequestBundle | None = None,
    ) -> bool:
        """Commit job result only if seq is greater than or equal to existing stored seq."""
        existing = self._records.get(key)
        if existing and existing.seq > seq:
            return False

        self._records[key] = record
        if bundle is not None:
            if key in self._bundles:
                self._bundles.move_to_end(key)
            self._bundles[key] = bundle
            while len(self._bundles) > self._capacity:
                self._bundles.popitem(last=False)
        return True
