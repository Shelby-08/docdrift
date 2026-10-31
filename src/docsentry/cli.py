"""`python -m docsentry.cli replay|evaluate` - local, offline, read-only."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from docsentry.intelligence.reporting.json_exporter import to_json
from docsentry.replay.evaluate import evaluate, load_manifest, to_markdown
from docsentry.replay.git_source import GitError
from docsentry.replay.runner import analyze_local
from docsentry.reporting.check_run import build_report


def _emit(text: str, out: str | None) -> None:
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


def cmd_replay(args: argparse.Namespace) -> int:
    res = analyze_local(args.repo, args.base, args.head)
    rep = build_report(res)
    if args.format == "json":
        doc = {"report": rep.model_dump(mode="json"), "analysis": json.loads(to_json(res))}
        _emit(json.dumps(doc, sort_keys=True, indent=2), args.out)
    else:
        lines = [rep.summary, "", f"Conclusion: {rep.conclusion}"]
        for a in rep.annotations:
            lines.append(
                f"- {a.path}:{a.start_line}-{a.end_line} [{a.annotation_level}] {a.message}"
            )
        _emit("\n".join(lines), args.out)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest).read_text(encoding="utf-8"))
    report = evaluate(manifest)
    text = (
        json.dumps(report, sort_keys=True, indent=2)
        if args.format == "json"
        else to_markdown(report)
    )
    _emit(text, args.out)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="docsentry.cli", description="DocSentry local replay tools")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("replay", help="analyze base..head of a local git repo")
    r.add_argument("--repo", required=True)
    r.add_argument("--base", required=True)
    r.add_argument("--head", required=True)
    r.add_argument("--format", choices=["json", "markdown"], default="markdown")
    r.add_argument("--out")
    r.set_defaults(func=cmd_replay)
    e = sub.add_parser("evaluate", help="run a manifest of historical cases")
    e.add_argument("--manifest", required=True)
    e.add_argument("--format", choices=["json", "markdown"], default="markdown")
    e.add_argument("--out")
    e.set_defaults(func=cmd_evaluate)
    args = p.parse_args(argv)
    try:
        return int(args.func(args))
    except GitError as exc:
        sys.stderr.write(f"error: {exc.code}\n")
    except (OSError, ValueError, ValidationError) as exc:
        sys.stderr.write(f"error: {type(exc).__name__}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
