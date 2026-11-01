# DocDrift

> Your code changed. Your docs didn't. We catch it.

DocDrift is a GitHub App that checks every pull request for **documentation that the PR just made
wrong**: a changed default, a removed or renamed parameter, a renamed config key, a deleted
function. It reports the exact documentation sentence, the exact code that contradicts it, and
links to both. It never edits your docs and never blocks a merge.

> Naming: the project is **DocDrift**. Its Python package, CLI module and Check Run label are still
> called `docsentry` (an earlier working name), so commands below use `docsentry`.

Built by **Team OS-hit!** for Hacktoberfest 2026 Hack Day, **Problem 05: Automated Documentation
Drift Detection**.

## Example

Code commit: `DEFAULT_TIMEOUT = 30` → `60`. The docs still say 30
([`examples/`](examples/) has the inputs and the script).

```
DocSentry: 1 newly introduced documentation drift finding

potential / R1  docs/settings.md:3
  "`DEFAULT_TIMEOUT` defaults to 30 seconds."
  Documentation says default 'DEFAULT_TIMEOUT' is 30 seconds but code has 60
  Code: src/client.py:1
```

With the optional local AI review switched on (real output, about 11 s on our laptop):

```
AI-assisted interpretation (advisory only)
- supports_drift, evidence: E1, E2. Documentation (E1) states DEFAULT_TIMEOUT defaults to
  30 seconds. Code (E2) defines DEFAULT_TIMEOUT as 60. This is a direct contradiction. ...
```

Full files: [`examples/demo_output.md`](examples/demo_output.md) and
[`examples/demo_output_qwen.md`](examples/demo_output_qwen.md).

## How it works

```
GitHub PR webhook ──▶ Retrieval ──▶ Analysis (deterministic) ──▶ Check Run
 (signature checked)   base + head     Python AST + Markdown      summary + annotations
                       snapshots       claims ↔ code, 4 rules     on the doc sentence
                                              │
                                              └──▶ optional local Qwen review (advisory)
```

1. **Webhook.** `POST /webhook` verifies the HMAC signature and accepts only PR events.
2. **Retrieval.** Builds a read-only bundle: PR metadata, changed files, and the **before** (merge
   base) and **after** (head) text of docs and Python files.
3. **Analysis.** Parses code with `ast` (repository code is never executed) and docs with a
   Markdown parser, extracts claims such as "defaults to 30 seconds", maps each claim to the code
   entity it talks about, compares before vs after, and applies the rules.
4. **Report.** One GitHub Check Run per head commit, with an annotation on the doc sentence.
   Conclusion is `success` or `neutral`, never `failure`.
5. **Optional AI review.** A local open-weight model reads the bounded evidence and explains the
   finding. It is advisory: it cannot create, delete or change a finding.

### What it detects

| Rule | Catches | Example |
|---|---|---|
| R1 | Default value no longer matches (unit-aware: seconds vs minutes) | docs say 30 s, code says 60 |
| R2 | Documented parameter was removed | docs mention `verbose`, function lost it |
| R3 | Config key renamed or removed | `DEFAULT_TIMEOUT` → `REQUEST_TIMEOUT` |
| R4 | Documented function/class renamed or removed | docs call `old_feature()` |

Only **newly introduced** drift is reported, so existing doc problems don't spam a PR.
Ambiguous matches become "uncertain" context instead of guesses.

## The AI model

| | |
|---|---|
| Model | **Qwen3.6-35B-A3B** (open-weight, GGUF `Q4_K_M`), mixture-of-experts with ~3B active parameters |
| Runtime | **llama.cpp** `llama-server`, OpenAI-compatible API on `127.0.0.1:8080`, fully local and offline |
| Job | Reads the quoted claim and code evidence for a finding and explains whether it supports drift, is likely consistent, or is uncertain. JSON output is schema-validated and must cite supplied evidence ids. |
| Switch | Off by default. `AI_REVIEW_ENABLED=true`, `AI_BACKEND=llama_cpp`, `OLLAMA_BASE_URL=http://127.0.0.1:8080` |
| Safety | Repository text is treated as untrusted data; loopback URLs only; no cloud model is ever called. |

**Design choice, stated plainly:** the deterministic engine decides what is a finding, because a
language model alone can invent drift or miss it. Qwen adds an explanation next to it. If the model
is down, slow or wrong, the findings are still published.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

pytest -q                          # 342 tests
python examples/run_demo.py        # the demo above, no GitHub needed
```

Check any two commits of a local repo, no GitHub App required:

```bash
python -m docsentry.cli replay --repo PATH --base <old-commit> --head <new-commit>
python -m docsentry.cli replay --repo PATH --base A --head B --ai     # + local Qwen review
python -m docsentry.cli evaluate --manifest cases.json                 # score on historical cases
```

Start the local model for `--ai`:

```bash
llama-server -m Qwen3.6-35B-A3B-UD-Q4_K_M.gguf -ngl 99 --n-cpu-moe 99 -c 16384 -fa on --jinja \
  --host 127.0.0.1 --port 8080
```

### Run as a GitHub App

1. Create a GitHub App with **Contents: read**, **Pull requests: read**, **Checks: write**,
   subscribed to *Pull request* events.
2. `cp .env.example .env` and fill in `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY`,
   `GITHUB_WEBHOOK_SECRET`. **Never commit `.env`**; it is git-ignored.
3. `python -m docsentry` and expose `POST /webhook` through a secure tunnel.
4. Run exactly **one** worker: queues, dedup and locks are in memory.

Everything else (all settings, the check-run lifecycle, failure codes, replay metrics) is in
[`docs/reference.md`](docs/reference.md), [`docs/retrieval.md`](docs/retrieval.md) and
[`docs/stage4-verification.md`](docs/stage4-verification.md).

## Quality

| Check | Result |
|---|---|
| Tests | 342 passing (`pytest -q`) |
| Lint | `ruff check .` clean |
| Types | `mypy src` clean, strict mode |
| CI | GitHub Actions runs all three on every PR and on `main`; no model or network is needed in CI |
| Process | Every change landed through a pull request using the PR template |

## Limitations (honest list)

- Python code and Markdown docs only.
- Claim extraction is pattern-based. In our demo, "`fetch` takes `retries`, which defaults to 3" after
  `retries=3 → 5` is **not** caught yet; changed constants like `DEFAULT_TIMEOUT` are.
- Type-contract changes (rule R5) and behavioural config (R6) are not implemented.
- Live GitHub behaviour (Checks: write approval, inline annotation rendering on unchanged lines,
  fork PRs) is **unverified on a real installation**; the analysis itself is verified offline and by
  `replay`.
- AI review has been verified live with llama.cpp only; the Ollama backend crashed on our RTX 5060
  and is untested.
- State is in memory, single process.

## Project layout

```
src/docsentry/
  github/        webhook, signature check, PR event, Check Run client
  retrieval/     read-only PR bundle: files, trees, before/after snapshots
  intelligence/  code_analysis · documentation · mapping · change_analysis · drift (rules)
  ai_review/     optional local-model review (llama.cpp / Ollama), validators
  replay/        offline git replay + evaluate CLI
  reporting/     Check Run summary and annotations
  jobs/          dedup, per-PR ordering, retries
examples/        demo project, real outputs, run_demo.py
docs/            reference and design notes
tests/           342 tests
```

## Team

**OS-hit!**: Shivansh Gaur, Ainish Singh, Riyansh Bhosale, Parth Jhawar.
AI coding assistants used (declared in each PR): Qwen3.6-35B-A3B (local, via the Antigravity SDK)
and Claude (via the Hermes agent). See [`HACKATHON.md`](HACKATHON.md).

## License

MIT, see [LICENSE](LICENSE).
