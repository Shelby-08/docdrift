# Examples: real inputs and real outputs

A tiny project where a code change makes one documentation sentence wrong.

| Path | What it is |
|---|---|
| `demo_project/before/` | The project before the change: `DEFAULT_TIMEOUT = 30`, and `docs/settings.md` says 30 seconds. |
| `demo_project/after/` | After the change: `DEFAULT_TIMEOUT = 60`. The docs were **not** updated. |
| `demo_output.md` | Real output of the deterministic engine. It points at `docs/settings.md:3` and `src/client.py:1`. |
| `demo_output_qwen.md` | Real output with the optional local AI review on (Qwen3.6-35B-A3B via llama.cpp, about 11 s). |
| `run_demo.py` | Rebuilds the two commits in a temporary git repo and runs `docsentry replay` on them. |

Reproduce:

```bash
python examples/run_demo.py                 # deterministic engine only
python examples/run_demo.py --ai            # plus local Qwen review (start D:\models\run-qwen.bat first)
```
