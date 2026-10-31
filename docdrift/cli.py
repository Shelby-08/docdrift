"""Command-line entry point for DocDrift.

The `check` command (diff -> doc search -> Qwen judge -> report) is added
in the following pull requests; this module sets up the CLI skeleton.
"""

from __future__ import annotations

import argparse

from docdrift import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docdrift",
        description="Find documentation sentences that a code change made wrong.",
    )
    parser.add_argument(
        "--version", action="version", version=f"docdrift {__version__}"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
