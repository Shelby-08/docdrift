# Stage 2: Pull Request Bundle Retrieval Pipeline

## Architecture

DocSentry's retrieval pipeline ingests incoming GitHub Pull Request webhooks, acquires scoped installation authentication via GitHub App tokens, and constructs a normalized, offline-deterministic `PullRequestBundle` containing:

1. **PullRequestContext**: Fully validated commit SHAs (`base_sha`, `head_sha`, `merge_base_sha`), repository coordinate metadata, and cross-fork indicators.
2. **ChangedFile List**: Paginated changed files list (capped at 3,000 files) categorized into `doc`, `source`, `config`, and `other`.
3. **Paired Snapshots**: Before (`base`) and after (`head`) text representations for modified and added documentation and source files with size limits (1MB per file, 10MB total budget) and binary / non-UTF-8 skip safeguards.
4. **Repository Tree Indices**: Base and head file trees captured recursively via the Git Trees API, with automatic non-recursive subtree fallback when `truncated=True`.
5. **Background Jobs & Concurrency**: In-memory LRU delivery tracker (`DeliveryTracker`), monotonic sequence-guarded job store (`BundleStore`), and retry / rate limit backoff manager (`JobManager`).

## Verification

- Run test suite: `pytest -q`
- Run offline bundle inspection: `python scripts/inspect_pr.py --offline`
