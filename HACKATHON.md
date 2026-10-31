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
**DocDrift** – *Your code changed. Your docs didn't. We catch it.*

Planned approach:
1. Read the pull request diff and extract user-visible changes (defaults, flags, parameters, removed functions).
2. Search the README and `docs/` for sentences that describe the changed code.
3. Use a local open-weight model to judge each candidate sentence as `outdated`, `still_correct` or `uncertain`, with a reason and a suggested fix.
4. Report the exact file, line, sentence and causing code change; run as a GitHub Actions check on every PR.

## AI models used

| Model | Where it runs | What it does in the product | Why we chose it |
|---|---|---|---|
| **Qwen3.6 35B-A3B** (`qwen3.6:35b`, open-weight) | Locally via Ollama | Judges whether each candidate documentation sentence is still correct after a code change, explains why, and writes a corrected sentence | Open-weight and runs fully offline on our laptop; strong at reading code and text together; mixture-of-experts design (~3B active parameters) makes it fast enough on an 8 GB GPU + 32 GB RAM laptop |

## AI coding assistants
- Claude (via the Hermes agent) helps write code; every pull request names the assistants used.
