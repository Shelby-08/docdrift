# Stage 3: Deterministic AST & Markdown Drift Analysis Engine

## Overview

DocSentry's Stage 3 intelligence engine detects documentation drift deterministically across code and markdown documentation:

1. **Python AST Extraction (`python_ast.py`)**: Uses Python's standard `ast` module (complemented by `tree-sitter-python`) to extract classes, functions, methods, parameters, types, defaults, and docstrings from both before (`base`) and after (`head`) snapshots.
2. **Markdown Parsing (`markdown_parser.py`)**: Uses `markdown-it-py` to parse markdown into structured blocks (`heading`, `code_block`, `paragraph`, `list_item`) and extract symbol mentions and function signature quotes with line numbers.
3. **Code-to-Doc Mapping (`mapper.py`)**: Maps code symbols to documentation files using explicit mentions (confidence 0.90) and file name proximity (confidence 0.70).
4. **Drift Detection (`detector.py` & `engine.py`)**:
   - **Stale References** (`critical`): Symbols removed or renamed in code but still referenced in docs.
   - **Broken Contracts** (`critical` / `warning`): Function signatures modified (required parameters added/removed, types changed) with outdated documentation quotes.
   - **Undocumented Changes** (`warning` / `info`): New or modified public symbols lacking documentation coverage.

## Verification

- Run test suite: `pytest -q`
- Run offline drift analysis: `python scripts/analyze_pr.py --offline`
