import os
from docsentry.intelligence.models import (
    CodeDocMapping,
    ExtractedClaim,
    SymbolSignature,
)


def map_code_to_documentation(
    source_symbols_by_file: dict[str, list[SymbolSignature]],
    claims: list[ExtractedClaim],
) -> list[CodeDocMapping]:
    """Map code symbols and source files to documentation files based on mentions and proximity."""
    mappings: list[CodeDocMapping] = []
    seen: set[tuple[str, str, str]] = set()

    # Index symbols by simple name and qualified name
    symbol_to_sources: dict[str, set[str]] = {}
    for src_file, syms in source_symbols_by_file.items():
        for s in syms:
            symbol_to_sources.setdefault(s.name, set()).add(src_file)
            symbol_to_sources.setdefault(s.qualified_name, set()).add(src_file)

    # 1. Explicit claim mentions (Confidence: 0.90)
    for claim in claims:
        target = claim.target_symbol
        if target in symbol_to_sources:
            for src_file in symbol_to_sources[target]:
                key = (src_file, claim.file_path, target)
                if key not in seen:
                    seen.add(key)
                    mappings.append(
                        CodeDocMapping(
                            source_file=src_file,
                            doc_file=claim.file_path,
                            matched_symbol=target,
                            confidence=0.90,
                            method="explicit_mention",
                        )
                    )

    # 2. File name proximity (e.g. docs/foo.md to src/foo.py) (Confidence: 0.70)
    for src_file, syms in source_symbols_by_file.items():
        src_base = os.path.splitext(os.path.basename(src_file))[0].lower()
        for claim in claims:
            doc_base = os.path.splitext(os.path.basename(claim.file_path))[0].lower()
            if src_base == doc_base or src_base in doc_base or doc_base in src_base:
                for s in syms:
                    key = (src_file, claim.file_path, s.name)
                    if key not in seen:
                        seen.add(key)
                        mappings.append(
                            CodeDocMapping(
                                source_file=src_file,
                                doc_file=claim.file_path,
                                matched_symbol=s.name,
                                confidence=0.70,
                                method="file_proximity",
                            )
                        )

    return mappings
