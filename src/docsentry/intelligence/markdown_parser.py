import re
from markdown_it import MarkdownIt
from markdown_it.token import Token

from docsentry.intelligence.models import (
    ClaimKind,
    DocBlock,
    DocBlockKind,
    ExtractedClaim,
)

SYMBOL_REGEX = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*(?:\(\))?)`")
CODE_SIG_REGEX = re.compile(r"(?:def|async def)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)")


def parse_markdown_blocks(file_path: str, markdown_text: str) -> list[DocBlock]:
    """Parse markdown into structured DocBlocks with headings context."""
    if not markdown_text.strip():
        return []

    md = MarkdownIt("commonmark")
    tokens = md.parse(markdown_text)
    blocks: list[DocBlock] = []
    current_heading: str | None = None

    idx = 0
    while idx < len(tokens):
        token = tokens[idx]

        if token.type == "heading_open":
            # Next token is inline with heading content
            idx += 1
            if idx < len(tokens):
                current_heading = tokens[idx].content.strip()
                line_start = token.map[0] + 1 if token.map else 1
                line_end = token.map[1] if token.map else line_start
                blocks.append(
                    DocBlock(
                        file_path=file_path,
                        block_kind="heading",
                        heading_context=current_heading,
                        line_start=line_start,
                        line_end=line_end,
                        content=current_heading,
                    )
                )
        elif token.type in ("fence", "code_block"):
            line_start = token.map[0] + 1 if token.map else 1
            line_end = token.map[1] if token.map else line_start
            blocks.append(
                DocBlock(
                    file_path=file_path,
                    block_kind="code_block",
                    heading_context=current_heading,
                    line_start=line_start,
                    line_end=line_end,
                    content=token.content,
                )
            )
        elif token.type == "paragraph_open":
            idx += 1
            if idx < len(tokens):
                content = tokens[idx].content
                line_start = token.map[0] + 1 if token.map else 1
                line_end = token.map[1] if token.map else line_start
                blocks.append(
                    DocBlock(
                        file_path=file_path,
                        block_kind="paragraph",
                        heading_context=current_heading,
                        line_start=line_start,
                        line_end=line_end,
                        content=content,
                    )
                )
        elif token.type == "list_item_open":
            # Scan child tokens for content
            line_start = token.map[0] + 1 if token.map else 1
            line_end = token.map[1] if token.map else line_start
            content_parts: list[str] = []
            idx += 1
            while idx < len(tokens) and tokens[idx].type != "list_item_close":
                if tokens[idx].content:
                    content_parts.append(tokens[idx].content)
                idx += 1
            blocks.append(
                DocBlock(
                    file_path=file_path,
                    block_kind="list_item",
                    heading_context=current_heading,
                    line_start=line_start,
                    line_end=line_end,
                    content=" \n".join(content_parts),
                )
            )

        idx += 1

    return blocks


def extract_claims_from_blocks(blocks: list[DocBlock]) -> list[ExtractedClaim]:
    """Extract claims, symbol mentions, and code quotes from DocBlocks."""
    claims: list[ExtractedClaim] = []

    for block in blocks:
        # 1. Code blocks checking for function/method definitions quotes
        if block.block_kind == "code_block":
            for match in CODE_SIG_REGEX.finditer(block.content):
                fn_name = match.group(1)
                full_sig = match.group(0)
                claims.append(
                    ExtractedClaim(
                        file_path=block.file_path,
                        line_number=block.line_start,
                        claim_kind="signature_quote",
                        target_symbol=fn_name,
                        extracted_text=full_sig,
                        context=block.heading_context,
                    )
                )

        # 2. Backtick symbol mentions in prose, headings, list items
        for match in SYMBOL_REGEX.finditer(block.content):
            symbol = match.group(1)
            # Strip trailing ()
            clean_symbol = symbol[:-2] if symbol.endswith("()") else symbol
            # Ignore short language keywords
            if clean_symbol in ("true", "false", "none", "str", "int", "dict", "list", "self", "bool"):
                continue
            claims.append(
                ExtractedClaim(
                    file_path=block.file_path,
                    line_number=block.line_start,
                    claim_kind="symbol_mention",
                    target_symbol=clean_symbol,
                    extracted_text=f"`{symbol}`",
                    context=block.heading_context,
                )
            )

    return claims
