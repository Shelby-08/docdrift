# Stage 4 verification matrix

Automated evidence is offline and uses fakes (PyGithub, Ollama) or throwaway local git repos.
Live GitHub and live Ollama behaviour is **UNVERIFIED** (see the end).

## Scenario to test matrix (spec S4-10)

| # | Scenario | Evidence | Status |
|---|---|---|---|
| 1 | Default 30 to 60, docs unchanged: one newly introduced finding, exact lines | `tests/test_replay.py::test_changed_default_exact_lines_and_evaluate_hits`, `tests/intelligence/test_pipeline.py::test_required_end_to_end_newly_introduced`, `tests/test_check_run_report.py::test_new_drift_annotates_unchanged_doc_sentence_with_head_permalink` | covered |
| 2 | Renamed flag, changed parameter, removed feature | `tests/test_replay.py::test_problem05_category_fixtures` (R3, R2, R4, R1) | covered; type changes are a gap (R5) |
| 3 | Doc corrected in the same change: no new drift | `tests/test_replay.py::test_doc_corrected_in_same_commit_no_new_drift`, controls test (`same_pr`) | covered |
| 4 | Docs-only and unrelated code: no findings | `tests/test_replay.py::test_controls_have_zero_findings` | covered |
| 5 | AI disabled: provider called zero times, deterministic run published | `tests/test_ai_review.py::test_disabled_and_no_items_make_zero_calls`, `tests/jobs/test_manager_publish.py::test_end_to_end_publish_with_ai_disabled` | covered |
| 6 | Ollama unavailable: findings still published, status shown, no unbounded retry | `test_ai_review.py::test_failures_map_to_status_without_raising`, `::test_retries_bounded_and_not_for_invalid_output`, `test_manager_publish.py::test_ai_unavailable_status_shown_and_findings_kept` | covered; auto-download is impossible (no pull code exists) |
| 7 | Prompt injection cannot alter instructions, IDs, URLs, status | `test_ai_review.py::test_hostile_text_only_in_user_payload_and_system_is_static`, `::test_models_strict` (URLs rejected), validator allow-lists | partially covered: model obedience itself cannot be tested offline |
| 8 | Hallucinated evidence, IDs, candidates rejected | `test_ai_review.py::test_validator_rules`, `::test_failures_map_to_status_without_raising`, `::test_ambiguous_suggestion_only_from_candidates` | covered |
| 9 | Ambiguous mapping: only supplied candidate, Stage 3 stays ambiguous, advisory | `test_ai_review.py::test_ambiguous_suggestion_is_advisory_only` | covered |
| 10 | Incomplete result: AI skipped, report says partial, never clean success | `test_ai_review.py::test_incomplete_input_is_skipped_visibly`, `test_check_run_report.py::test_incomplete_never_success` | covered |
| 11 | Duplicate webhook, out-of-order jobs, stale snapshot | `test_manager_publish.py::test_duplicate_delivery_one_run_one_analysis`, `::test_redelivery_same_head_does_not_create_second_run`, `::test_stale_via_newer_job_cancels_own_run_only`, `::test_live_head_recheck_detects_stale_snapshot`, `::test_head_recheck_failure_never_assumes_currency` | covered |
| 12 | More than 50 annotations, caps, unchanged-line annotation, no pre-existing annotations | `tests/test_checks_adapter.py::test_annotation_batches_of_50_no_duplicates_and_single_completion`, `test_check_run_report.py::test_grouping_cap_omitted_and_order`, `::test_pre_existing_not_annotated_or_counted` | covered |
| 13 | Fork or inaccessible head: safe status, not reported published | `test_manager_publish.py::test_fork_unavailable_is_not_reported_published`, `test_checks_adapter.py::test_failure_classes_map_to_safe_codes` | covered with fakes; real fork response unverified |
| 14 | Invalid model output: only a safe status code shown | `test_ai_review.py::test_failures_map_to_status_without_raising`; `AIReviewResult` has no raw-output field and the report prints only status and code | covered by construction plus test |
| 15 | Loopback-only: DNS hosts, proxies, redirects rejected | `test_ai_review.py::test_non_loopback_rejected`, `::test_opener_disables_proxies_and_redirects`, `::test_client_rejects_non_loopback_before_any_request` | covered |
| 16 | Single process stated in README and config docs | README "Single process only"; comment in `.env.example` | documented (no test) |
| 17 | `replay` / `evaluate` reproduce 1 to 4 from local git, no network | `tests/test_replay.py` (all fixtures, `test_no_write_or_network_git_commands_and_no_sockets`, `test_cli_replay_and_evaluate_deterministic`) | covered |

## Verified facts (installed source)

- PyGithub 2.8.1: `Repository.create_check_run(name, head_sha, details_url, external_id, status,
  started_at, conclusion, completed_at, output, actions)`, `CheckRun.edit(...)` with the same fields,
  `Commit.get_check_runs(check_name, status, filter)`.
- Ollama: installed, `/api/tags` returned no models, so the `/api/chat` contract was not probed.

## UNVERIFIED (needs a live installation)

- Checks: write approval and real Check Run creation and updates.
- Annotation rendering on lines outside the PR diff, and whether later edits append annotations.
- Fork PR behaviour.
- Ollama JSON-schema `format`, `think`, and real model quality.
