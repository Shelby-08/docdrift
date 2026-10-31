# DocSentry

## Overview
DocSentry is a GitHub App backend designed to detect documentation drift in Pull Requests.
It receives webhooks, validates payloads, and prepares the context for analysis.

## Current Stage
**Stage 1: Backend Foundation, Stage 2: PR retrieval, Stage 3: Drift analysis**
- Webhook ingestion
- Signature verification
- Payload validation
- Logging

## Setup
1. Create a virtual environment: `python -m venv .venv`
2. Install dependencies: `pip install -e ".[dev]"`
3. Copy `.env.example` to `.env` and fill in the values.

## Environment Variables
- `GITHUB_APP_ID`: Your GitHub App ID.
- `GITHUB_PRIVATE_KEY`: Your RSA Private Key.
- `GITHUB_WEBHOOK_SECRET`: Secret for webhook verification.
- `PORT`: Port to run the server (default 3000).

## Running
Run the server:
```bash
python -m docsentry
```

## Stage 3: Deterministic Drift Analysis

Stage 3 compares documentation with code at the **merge base** (before) and the PR **head**
(after) and reports where documentation no longer matches the code. It is a pure, offline
core: no LLM, no network, no database, no GitHub writes, and repository code is never executed
(`ast.parse` plus a safe literal evaluator only).

**Design.** `load_snapshots` (the only module touching Stage 2) turns a `PullRequestBundle`
into two immutable `RepoSnapshot`s. `analyze_repositories(base, head, ctx, limits)` is a pure
function: classify -> parse code -> symbol index + default resolution + dependency graph ->
parse docs -> extract claims -> map claims to code (per side) -> match entities + semantic diff
-> drift rules + temporal classification -> `AIReviewInput`. `analyze_bundle` = load + analyze.

**Supported.** Code: Python only. Docs: `.md` and `.markdown`. Other languages/doc formats are
recorded in `skipped_files` and mark the result incomplete.

**Rules.** R1 default value mismatch (with unit conversion), R2 removed parameter,
R3 renamed/removed config key, R4 renamed/removed symbol. R5 (type contract) and R6 (behavioural
config) are **not implemented**.

**Temporal status** (`before` = merge base, `after` = head):

| Base | Head | Result |
| --- | --- | --- |
| consistent | consistent | no drift (counted only) |
| consistent | inconsistent | `newly_introduced` |
| inconsistent | consistent | `resolved` |
| inconsistent | inconsistent | `pre_existing` (only if touched, else counted as untouched) |
| not evaluable | inconsistent | `newly_introduced` if claim/entity touched, else `indeterminate` |
| any | not evaluable | `insufficient_evidence` finding only if touched |

**Limits** (env vars): `ANALYSIS_MAX_SOURCE_FILES`, `ANALYSIS_MAX_DOC_FILES`,
`ANALYSIS_MAX_UNCHANGED_SOURCE_FILES`, `ANALYSIS_TIME_BUDGET_SECONDS`, `ANALYSIS_MAX_GRAPH_DEPTH`,
`ANALYSIS_MAX_GRAPH_NODES`, `ANALYSIS_MAX_CANDIDATES_PER_CLAIM`, `ANALYSIS_INCLUDE_FULL_ENTITIES`,
`AI_REVIEW_MAX_ITEMS`.

**AI handoff.** `AnalysisResult.ai_review_input` lists bounded, priority-ordered items
(uncertain findings, ambiguous relationships, indirect dependencies, behavioural candidates)
plus a fixed notice that all quoted text is untrusted repository data.

**Manual live check** (read-only GETs, prints counts only; not run by the test suite):
`python scripts/analyze_pr.py --installation-id ID --owner OWNER --repo NAME --pr N [--out result.json] [--include-texts]`
(output goes under `.docsentry-out/`).

**Current limitations.** Python-only code analysis; conservative regex claim patterns; table
cell lines are per row only; no cross-file dynamic imports (`getattr`, `importlib`, strings);
no semantic reasoning; results are in memory only (not wired into the webhook job, not
durable); `test_file` skips are recorded but do not reduce completeness; the engine has only
been exercised on synthetic fixtures and Stage 2's live GitHub path is unverified.

## License
MIT, see [LICENSE](LICENSE).

