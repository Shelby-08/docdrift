import logging
from docsentry.intelligence.detector import detect_drift
from docsentry.intelligence.markdown_parser import (
    extract_claims_from_blocks,
    parse_markdown_blocks,
)
from docsentry.intelligence.mapper import map_code_to_documentation
from docsentry.intelligence.models import (
    DocBlock,
    DriftAnalysisReport,
    ExtractedClaim,
    SymbolChange,
    SymbolSignature,
)
from docsentry.intelligence.python_ast import (
    diff_symbol_signatures,
    extract_python_symbols,
)
from docsentry.retrieval.models import PullRequestBundle

logger = logging.getLogger(__name__)


def analyze_bundle_drift(bundle: PullRequestBundle) -> DriftAnalysisReport:
    """Analyze documentation drift from a PullRequestBundle."""
    all_symbol_changes: list[SymbolChange] = []
    source_symbols_by_file: dict[str, list[SymbolSignature]] = {}
    all_blocks: list[DocBlock] = []
    all_claims: list[ExtractedClaim] = []

    # 1. Process source snapshots (Python)
    for snap in bundle.snapshots:
        if snap.category == "source" and snap.path.endswith(".py"):
            before_text = snap.base.text if (snap.base and not snap.base.missing) else ""
            after_text = snap.head.text if (snap.head and not snap.head.missing) else ""

            before_syms = extract_python_symbols(before_text) if before_text else []
            after_syms = extract_python_symbols(after_text) if after_text else []
            source_symbols_by_file[snap.path] = after_syms or before_syms

            changes = diff_symbol_signatures(snap.path, before_syms, after_syms)
            all_symbol_changes.extend(changes)

    # 2. Process documentation snapshots (Markdown)
    for snap in bundle.snapshots:
        if snap.category == "doc" and snap.path.endswith(frozenset({".md", ".markdown"})) or (
            snap.category == "doc" and (snap.path.endswith(".md") or snap.path.endswith(".markdown"))
        ):
            doc_text = snap.head.text if (snap.head and not snap.head.missing) else ""
            if not doc_text and snap.base and not snap.base.missing:
                doc_text = snap.base.text
            if doc_text:
                blocks = parse_markdown_blocks(snap.path, doc_text)
                all_blocks.extend(blocks)
                claims = extract_claims_from_blocks(blocks)
                all_claims.extend(claims)

    # 3. Map code to documentation
    mappings = map_code_to_documentation(source_symbols_by_file, all_claims)

    # 4. Detect drift
    report = detect_drift(all_symbol_changes, all_claims, mappings, all_blocks)
    return report
