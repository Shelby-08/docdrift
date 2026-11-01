"""Reproducible demo: build a tiny git repo whose second commit makes a doc sentence wrong,
then run DocSentry on it.

    python examples/run_demo.py > examples/demo_output.md
    python examples/run_demo.py --ai > examples/demo_output_qwen.md   (needs llama-server on :8080)
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent / "demo_project"
GIT = [
    "git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", "-c", "core.autocrlf=false",
]


def git(repo: Path, *args: str) -> None:
    subprocess.run([*GIT, "-C", str(repo), *args], check=True, capture_output=True)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "demo_project"
        shutil.copytree(HERE / "before", repo, copy_function=shutil.copy)
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "before: timeout is 30 and the docs say 30")
        shutil.copytree(HERE / "after", repo, dirs_exist_ok=True, copy_function=shutil.copy)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "code: raise DEFAULT_TIMEOUT to 60 (docs not updated)")
        result = subprocess.run(
            [sys.executable, "-m", "docsentry.cli", "replay", "--repo", str(repo),
             "--base", "HEAD~1", "--head", "HEAD", "--format", "markdown", *sys.argv[1:]],
            capture_output=True, text=True, check=True,
        )
        sys.stdout.write(result.stdout)


if __name__ == "__main__":
    main()
