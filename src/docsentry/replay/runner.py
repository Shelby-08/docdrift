"""Run the real Stage 3 engine on two local commits (no GitHub, no network)."""

from datetime import UTC, datetime

from docsentry.intelligence.models.analysis import AnalysisContext, AnalysisResult
from docsentry.intelligence.models.common import AnalysisLimits
from docsentry.intelligence.pipeline import analyze_repositories
from docsentry.intelligence.repository.loader import load_snapshots
from docsentry.replay.git_source import Git, GitFileSource, build_local_bundle, repo_name


def analyze_local(
    repo: str,
    base: str,
    head: str,
    limits: AnalysisLimits | None = None,
    max_file_bytes: int = 1_000_000,
    git: Git | None = None,
) -> AnalysisResult:
    lim = limits or AnalysisLimits()
    g = git or Git(repo)
    bundle = build_local_bundle(g, base, head, repo_name(repo))
    b, h = load_snapshots(bundle, GitFileSource(g, max_file_bytes), lim)
    c = bundle.context
    ctx = AnalysisContext(
        owner=c.owner,
        repository=c.repository,
        repository_id=c.repository_id,
        pull_number=c.pull_number,
        base_sha=b.commit_sha,
        head_sha=h.commit_sha,
        original_base_sha=c.base_sha,
        delivery_id=c.delivery_id,
    )
    renames = {
        cf.previous_filename: cf.filename for cf in bundle.changed_files if cf.previous_filename
    }
    return analyze_repositories(b, h, ctx, lim, lambda: datetime.fromtimestamp(0, UTC), renames)
