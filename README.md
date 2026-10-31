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

## Stage 4: Check Run reporting, replay CLI, optional local AI review

**Adds.** (1) A GitHub **Check Run** (summary + annotations) per analysed PR head SHA. (2) A local
`replay` / `evaluate` CLI that runs the real Stage 3 engine on any two commits of a local git repo.
(3) An optional, advisory, local Ollama review layer (off by default).
**Does not add.** Comments, reviews, statuses, pushes, doc edits, a dashboard, a database, new
dependencies, cloud LLMs, or new Stage 3 rules. The only GitHub write is the DocSentry Check Run.

**Authority.** Stage 3 is deterministic and authoritative. AI output is advisory: it cannot create,
delete, suppress or upgrade findings, cannot make an ambiguous mapping unique and cannot change
statuses, paths, lines or links. Ollama being absent, slow or returning garbage never removes
deterministic findings.

### Single process only
Queues, delivery dedup, per-PR sequence numbers and per-SHA locks are in memory. Run exactly
**one Uvicorn worker** (`--workers 1`). State is lost on restart.

### Check Run lifecycle
Per verified bundle: find or create one `in_progress` run named `DOCSENTRY_CHECK_NAME` on the exact
head SHA (matched by exact SHA and `external_id` = hash of repo id + PR number + head SHA), run
Stage 3, run the AI seam, build the report, re-check that the PR head is still that SHA, then
complete the run (annotations are sent in batches of 50; later edits append). If a newer delivery
arrived or the live head changed, that SHA's own run is completed as `cancelled` and nothing is
published as current. If the head re-check fails, currency is not assumed (run cancelled, status
`head_recheck_failed`). Re-running a check from the GitHub UI is not supported (no Check Run webhooks).

**Conclusion** is `success` only when analysis is complete and there are zero newly introduced
confirmed/potential findings; otherwise `neutral`. Never `failure`; no approvals.

**Annotations** target the exact documentation sentence in the head commit (verified against the
head claims), level `warning` (confirmed) or `notice` (potential); one per doc sentence; capped by
`DOCSENTRY_MAX_ANNOTATIONS`. Pre-existing, ambiguous and insufficient-evidence findings appear in the
summary only. Caveat: when the doc sentence is not in the PR diff, GitHub lists the annotation on
the Checks tab but may not render it inline in *Files changed*. This is **unverified live**; the
summary always carries immutable permalinks (base-side evidence uses the merge-base SHA, head-side
the head SHA).

### Failure behaviour
Safe codes: `github_checks_permission_missing`, `github_auth_failed`, `github_rate_limited`,
`github_check_unavailable_for_head` (fork or inaccessible head: never reported as published; fork
support is unverified), `github_check_publish_failed`. A bad annotation (HTTP 422) falls back to a
summary-only completion. Publishing failure never discards the analysis; `JobRecord.publish_status`
and `publish_code` record the outcome. An analysis crash completes the run `neutral` with a generic
message.

### GitHub App permissions
Contents: read, Pull requests: read, **Checks: write**. Adding Checks: write requires the owner to
approve the permission change on the installation (reinstall or approve). Webhooks must reach
`POST /webhook` through a secure tunnel or deployment. Never expose Ollama's port 11434.

### Environment variables (defaults)
| Variable | Default | Notes |
|---|---|---|
| `DOCSENTRY_CHECK_NAME` | `DocSentry` | stable check name |
| `DOCSENTRY_MAX_ANNOTATIONS` | `25` | 1..100 (API calls send at most 50) |
| `DOCSENTRY_MAX_SUMMARY_FINDINGS` | `30` | 1..100 |
| `DOCSENTRY_PUBLISH_ENABLED` | `true` | `false` = analyse only, no GitHub writes |
| `AI_REVIEW_ENABLED` | `false` | opt-in; `false` = zero Ollama requests |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | loopback IP literal only (`127.0.0.1` or `[::1]`) |
| `OLLAMA_MODEL` | (empty) | required when AI is enabled; empty keeps AI off and logs a warning |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | 1..300 |
| `OLLAMA_NUM_CTX` | `8192` | 1..16384 |
| `AI_REVIEW_TOTAL_BUDGET_SECONDS` | `180` | 1..600 across all batches |
| `AI_REVIEW_MAX_BATCH_ITEMS` | `5` | 1..10 |
| `AI_REVIEW_MAX_BATCH_CHARS` | `12000` | 1..30000 |
| `AI_REVIEW_MAX_OUTPUT_TOKENS` | `1200` | 1..4000 |
| `AI_REVIEW_MAX_RETRIES` | `0` | 0..1, transient transport errors only |

Model concurrency is a constant of 1. Stage 3 limits are unchanged.

### Local AI review (optional)
No `ollama` package and no cloud LLM: a small stdlib client talks to `POST /api/chat` on loopback
with a no-proxy opener that rejects every redirect. The system prompt is static; repository text only
appears inside the quoted JSON user message. Output is schema-validated (`extra=forbid`), checked
against per-item evidence-id allow-lists, URLs are rejected, `supports_drift` or `likely_consistent`
without valid evidence is downgraded to `uncertain`, and `suggested_target_id` is accepted only for
ambiguous-relationship items from the supplied candidates. Prompt version: `1`.

Setup: install Ollama, run `ollama pull <tag>` yourself (DocSentry never pulls), check `ollama list`
and that the model fits your RAM/VRAM (large MoE models are mostly offloaded to system RAM and are
slow), then set `OLLAMA_MODEL=<tag>` and `AI_REVIEW_ENABLED=true`. Optionally keep the model warm
with Ollama's `OLLAMA_KEEP_ALIVE`. Model output is non-deterministic and advisory.

Dev machine status: Ollama is installed but has **no models pulled**, so the live `/api/chat`
contract (JSON-schema `format`, `think`) is **unverified**. `think` is never sent; the client falls
back from schema `format` to `"json"` on HTTP 400.

### Replay and evaluate (offline, read-only git)
```
python -m docsentry.cli replay --repo PATH --base REV --head REV [--format json|markdown] [--out FILE]
python -m docsentry.cli evaluate --manifest cases.json [--format json|markdown] [--out FILE]
```
Manifest: a JSON list of `{id, kind: "drift"|"control", repo_path, base, code_commit, doc_fix_commit?}`.
Only `rev-parse`, `merge-base`, `diff`, `cat-file` and `ls-tree` are ever run (fixed argv, no shell,
`GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_NOSYSTEM=1`); revisions are validated and `--end-of-options` is
used. Local bundles are marked `delivery_id` / `owner` = `local_git`; GitHub-only ids use sentinel
value `1`, which Stage 3 ignores. Metrics: path hit (a newly introduced finding is in a doc file
changed by the fix commit), line hit (only when the doc blob is unchanged between the code commit and
the fix's parent, else "unavailable"), findings per case and per control case, path and line recall.

### Problem 05 coverage
| Category | Rule | Test | Gap |
|---|---|---|---|
| Renamed config flag/option | R3 (constants), R4 (symbols) | `tests/test_replay.py` `renamed_flag` | R3 covers constant-style names |
| Changed default | R1 (unit-aware) | `test_changed_default...`, `param_default` | unqualified phrasing gives `potential` |
| Changed API parameter | R2 removed or renamed (confirmed), R1 default | `param_removed`, `param_default` | **type changes: R5 not implemented** |
| Removed feature/symbol | R4 | `removed_feature` | dynamic or string references are not seen |

Indirect doc/code relations go through the dependency graph and surface as AI-review items, never as
confirmed findings. False alarms are limited by: only newly introduced confirmed/potential findings
count, ambiguous and insufficient-evidence findings are context only, redefined or overloaded
functions are never confirmed, private entities are low relevance.

### Manual acceptance checklist and 3-minute demo
1. Install the App on a throwaway repo (Contents and Pull requests read, Checks write) and start one
   Uvicorn worker.
2. Open a PR changing `DEFAULT_TIMEOUT` 30 to 60 with docs still saying 30: expect one annotation on
   the doc sentence and a code permalink, and no doc edit.
3. Open a PR changing code and docs together: no new drift.
4. Run `python -m docsentry.cli evaluate` on a manifest: show path/line recall and findings on controls.
5. Optionally enable AI with a pulled model and compare.
6. Stop Ollama and re-run: findings still publish, AI shown unavailable, `/health` fine.
7. Redeliver a webhook: no second run. Push a newer commit: the older job cannot touch the new run.
8. Check logs contain no repo text or secrets.

**UNVERIFIED (needs a live installation):** Checks: write approval, real Check Run creation,
annotation rendering on unchanged lines, fork PR behaviour, Ollama schema `format`.

## License
MIT, see [LICENSE](LICENSE).

