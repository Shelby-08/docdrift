# HACKATHON.md

## Team name
OS-hit!

## Team members
1. Shivansh Gaur
2. Ainish Singh
3. Riyansh Bhosale
4. Parth Jhawar

## Problem statement
**Problem 05 – Automated Documentation Drift Detection**

Build a CI check that finds the documentation sentences a pull request just made wrong
(renamed flags, changed defaults, changed parameters, removed features), points to the
exact sentence and the exact code change responsible, and suggests a correction.

## Project
**DocDrift** (repository `docdrift`; Python package `docsentry`) – *Your code changed. Your docs didn't. We catch it.*

> Update: the first commit described an early plan. The built project is **DocDrift**, a GitHub App
> (its Python package is still called `docsentry`, an earlier working name). The description below is
> what the code does today.

How it works:
1. A GitHub webhook for a pull request arrives (HMAC signature verified).
2. The app reads the **before** (merge base) and **after** (head) versions of Python files and
   Markdown docs, read-only.
3. A **deterministic engine** (Python `ast` + Markdown parser) extracts documentation claims such as
   "defaults to 30 seconds", maps them to the code they describe, and applies rules: R1 changed
   default, R2 removed parameter, R3 renamed/removed config key, R4 renamed/removed symbol. Only
   newly introduced drift is reported.
4. A GitHub **Check Run** reports the exact documentation sentence, the contradicting code, and
   permalinks to both, as annotations on the doc sentence. It never edits docs or blocks a merge.
5. An **optional local AI review** (off by default) explains each finding and cites the evidence.

An offline `replay` / `evaluate` CLI runs the same engine on any two commits of a local git repo.
Real inputs and outputs are in `examples/`.

## AI models used

| Model | Where it runs | What it does in the product | Why we chose it |
|---|---|---|---|
| **Qwen3.6 35B-A3B** (open-weight; GGUF `Qwen3.6-35B-A3B-UD-Q4_K_M`) | Locally via **llama.cpp** (`llama-server`, OpenAI-compatible API on `127.0.0.1:8080`) | Optional, advisory review of each drift finding: reads the quoted claim and the code evidence and returns a schema-validated verdict (`supports_drift`, `likely_consistent` or `uncertain`) with an explanation that must cite the supplied evidence. Enabled with `AI_REVIEW_ENABLED=true`, `AI_BACKEND=llama_cpp`. Real output: `examples/demo_output_qwen.md` (about 11 s per run). | Open-weight and fully offline; strong at reading code and prose together; mixture-of-experts with ~3B active parameters keeps it usable on an 8 GB GPU + 32 GB RAM laptop |

How the model is used, stated plainly: the deterministic engine decides what is a finding. Qwen
cannot create, delete or change findings; it adds an explanation next to each one. If the model is
unavailable, findings are still published. No cloud model is ever called by the product.

> The first commit said "via Ollama". We run the same model through llama.cpp instead, because
> importing the GGUF into Ollama crashed its CUDA backend on our RTX 5060.

## AI coding assistants
- **Qwen3.6-35B-A3B** (local, via llama.cpp, driven through the Antigravity SDK) drafted much of the code.
- **Claude** (via the Hermes agent) reviewed, fixed and extended code, and wrote documentation.
- Every pull request names the assistants used in its template.
