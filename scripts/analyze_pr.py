#!/usr/bin/env python3
"""Manual live check of the Stage 3 analysis engine against a real pull request.

Usage:
    python scripts/analyze_pr.py --installation-id 123 --owner OWNER --repo NAME --pr 7 \
        [--out result.json] [--include-texts]

Performs GET requests only. Prints COUNTS ONLY. With --out, writes the JSON result under
.docsentry-out/. NOT part of the test suite.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from docsentry.config import load_settings
from docsentry.intelligence.pipeline import analyze_bundle
from docsentry.intelligence.reporting.json_exporter import to_json
from docsentry.models import PullRequestEventContext
from docsentry.retrieval.auth import GitHubAuthService
from docsentry.retrieval.bundle_builder import build_pull_request_bundle
from docsentry.retrieval.snapshots import GitHubFileReader

OUT_DIR = Path(".docsentry-out")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a pull request (live, read-only)")
    parser.add_argument("--installation-id", type=int, required=True)
    parser.add_argument("--owner", type=str, required=True)
    parser.add_argument("--repo", type=str, required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--out", type=str, default=None, help="file name under .docsentry-out/")
    parser.add_argument("--include-texts", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    client = GitHubAuthService(settings).client_for_installation(args.installation_id)
    repo = client.get_repo(f"{args.owner}/{args.repo}")
    event = PullRequestEventContext(
        action="synchronize",
        owner=args.owner,
        repo=args.repo,
        repo_id=int(repo.id),  # the bundle builder verifies the repository id
        pr_number=args.pr,
        installation_id=args.installation_id,
        base_sha="0" * 40,
        head_sha="0" * 40,
        title="",
        delivery_id="cli-analyze",
    )
    bundle = build_pull_request_bundle(client, event, settings)
    result = analyze_bundle(bundle, GitHubFileReader(repo, settings), settings)

    summary = {
        "complete": result.complete,
        "incomplete_reasons": list(result.incomplete_reasons),
        "findings_by_evidence_status": dict(
            Counter(f.evidence_status.value for f in result.findings)
        ),
        "findings_by_temporal_status": dict(
            Counter(f.temporal_status.value for f in result.findings)
        ),
        "skipped_by_reason": dict(Counter(s.reason for s in result.skipped_files)),
        "ai_review_items": len(result.ai_review_input.items),
        "ai_review_omitted": result.ai_review_input.omitted_count,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.out:
        name = Path(args.out).name
        OUT_DIR.mkdir(exist_ok=True)
        target = OUT_DIR / name
        target.write_text(to_json(result, include_texts=args.include_texts), encoding="utf-8")
        print(f"wrote {target}")
    sys.exit(0)


if __name__ == "__main__":
    main()
