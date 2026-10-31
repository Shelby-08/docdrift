# DocDrift

> Your code changed. Your docs didn't. We catch it.

DocDrift is a CI check that finds the documentation sentences a pull request just made wrong
(renamed flags, changed defaults, changed parameters, removed features). It points to the
exact sentence and the exact code change, and suggests a corrected sentence.
A local open-weight model (**Qwen3.6 35B-A3B via Ollama**) judges each candidate sentence.

Built by **Team OS-hit!** for Hacktoberfest 2026 Hack Day (Problem 05).

## Status
Work in progress: project setup, licence, PR template and CI are in place.
The detection pipeline lands in the next pull requests.

## Install (development)
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install -e ".[test]"
pytest
docdrift --version
```

## Licence
MIT, see [LICENSE](LICENSE).
