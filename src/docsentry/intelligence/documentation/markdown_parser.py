"""Markdown parsing into leaf blocks, statements, tables, code blocks and links."""

import hashlib
import posixpath
import re
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

from docsentry.intelligence.documentation.sentence_extractor import (
    normalize_ws,
    split_sentences,
)
from docsentry.intelligence.models.documentation import (
    CodeBlockRef,
    DocBlock,
    DocLink,
    DocStatement,
    DocTable,
    ParsedDocument,
    TableCellRef,
)

_NEWLINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n|$)")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_CAPS = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
_IMPORT = re.compile(r"^\s*import\s+([\w., ]+)", re.MULTILINE)
_FROM = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+([\w, ]+)", re.MULTILINE)


def _hash(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def _split_lines(text: str) -> list[str]:
    lines = _NEWLINE.findall(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _blank_front_matter(text: str) -> tuple[str, bool]:
    if not (text.startswith("---\n") or text.startswith("---\r\n")):
        return text, False
    lines = _split_lines(text)
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n").strip() == "---":
            blanked = "".join(re.sub(r"[^\r\n]", " ", ln) for ln in lines[: i + 1])
            return blanked + "".join(lines[i + 1 :]), True
    return text, False


def _identifiers(content: str, language: str | None) -> tuple[str, ...]:
    found: set[str] = set()
    found.update(_CALL.findall(content))
    found.update(_CAPS.findall(content))
    if language in (None, "", "python", "py"):
        for m in _IMPORT.finditer(content):
            found.update(p.strip().split(" as ")[0] for p in m.group(1).split(",") if p.strip())
        for m in _FROM.finditer(content):
            found.add(m.group(1))
            found.update(p.strip() for p in m.group(2).split(",") if p.strip())
    return tuple(sorted(found))


def classify_link(path: str, target: str) -> tuple[str, str | None]:
    if target.startswith("#"):
        return "anchor", None
    if target.startswith("//") or (_SCHEME.match(target) and not target.startswith("mailto:")):
        return "external", None
    if _SCHEME.match(target):
        return "other", None
    clean = re.split(r"[#?]", target, maxsplit=1)[0]
    if not clean:
        return "other", None
    if clean.startswith("/"):
        resolved = posixpath.normpath(clean.lstrip("/"))
    else:
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), clean))
    if resolved.startswith("..") or resolved == ".":
        return "relative_path", None
    return "relative_path", resolved


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    parts = _UNESCAPED_PIPE.split(stripped)
    if stripped.startswith("|") and parts:
        parts = parts[1:]
    if stripped.endswith("|") and not stripped.endswith("\\|") and parts:
        parts = parts[:-1]
    return [p.strip() for p in parts]


def parse_markdown(path: str, text: str, commit_sha: str) -> ParsedDocument:
    errors: list[str] = []
    try:
        return _parse(path, text, commit_sha, errors)
    except (RecursionError, ValueError, IndexError, TypeError) as exc:
        errors.append(f"markdown_parse_error:{type(exc).__name__}")
        return ParsedDocument(path=path, commit_sha=commit_sha, errors=tuple(errors))


def _parse(path: str, text: str, commit_sha: str, errors: list[str]) -> ParsedDocument:
    work_text, had_front = _blank_front_matter(text)
    if had_front:
        errors.append("front_matter_skipped")
    lines = _split_lines(text)
    starts: list[int] = []
    off = 0
    for ln in lines:
        starts.append(off)
        off += len(ln)

    def raw_slice(map_: list[int]) -> tuple[str, int]:
        a, b = map_[0], min(map_[1], len(lines))
        if a >= len(lines):
            return "", len(text)
        return "".join(lines[a:b]).rstrip("\r\n"), starts[a]

    md = MarkdownIt("commonmark").enable("table")
    env: dict[str, Any] = {}
    tokens = md.parse(work_text, env)

    blocks: list[DocBlock] = []
    statements: list[DocStatement] = []
    tables: list[DocTable] = []
    code_blocks: list[CodeBlockRef] = []
    links: list[DocLink] = []
    containers: list[str] = []
    heading_stack: list[tuple[int, str]] = []
    order = 0

    def heading_path() -> tuple[str, ...]:
        return tuple(t for _, t in heading_stack)

    def add_block(kind: Any, map_: list[int], token_type: str, hp: tuple[str, ...]) -> DocBlock:
        nonlocal order
        raw, _ = raw_slice(map_)
        block = DocBlock(
            block_id=_hash(path, order, map_[0]),
            path=path,
            kind=kind,
            container=tuple(containers),
            text=raw,
            heading_path=hp,
            line=map_[0] + 1,
            end_line=max(map_[1], map_[0] + 1),
            token_type=token_type,
            order=order,
        )
        order += 1
        blocks.append(block)
        return block

    def add_statements(block: DocBlock, map_: list[int], *, heading: bool, split: bool) -> None:
        raw, offset = raw_slice(map_)
        for sp in split_sentences(
            raw,
            offset,
            block.line,
            file_text=text,
            heading=heading,
            split=split,
        ):
            statements.append(
                DocStatement(
                    statement_id=_hash(block.block_id, sp.start),
                    block_id=block.block_id,
                    path=path,
                    text=sp.text,
                    raw_start=offset + sp.start,
                    raw_end=offset + sp.end,
                    line=sp.line,
                    column=sp.column,
                    end_line=sp.end_line,
                    location_verified=sp.verified,
                    heading_path=block.heading_path,
                )
            )

    def collect_links(inline: Token) -> None:
        if not inline.children:
            return
        line = (inline.map[0] + 1) if inline.map else 1
        current: dict[str, Any] | None = None
        for child in inline.children:
            if child.type == "link_open":
                current = {"href": str(child.attrs.get("href", "")), "text": ""}
            elif child.type == "link_close" and current is not None:
                kind, resolved = classify_link(path, current["href"])
                links.append(
                    DocLink(
                        path=path,
                        text=current["text"],
                        target=current["href"],
                        line=line,
                        kind=kind,
                        resolved_path=resolved,
                    )
                )
                current = None
            elif current is not None and child.type in ("text", "code_inline"):
                current["text"] += child.content

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        t = tok.type
        if t == "blockquote_open":
            containers.append("blockquote")
        elif t == "blockquote_close":
            if "blockquote" in containers:
                containers.pop(len(containers) - 1 - containers[::-1].index("blockquote"))
        elif t == "list_item_open":
            containers.append("list_item")
        elif t == "list_item_close":
            if "list_item" in containers:
                containers.pop(len(containers) - 1 - containers[::-1].index("list_item"))
        elif t == "heading_open" and tok.map:
            level = int(tok.tag[1:]) if tok.tag[1:].isdigit() else 1
            inline = tokens[i + 1] if i + 1 < n else None
            title = normalize_ws(inline.content) if inline is not None else ""
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            block = add_block("heading", tok.map, t, heading_path())
            add_statements(block, tok.map, heading=True, split=False)
            if inline is not None:
                collect_links(inline)
            i += 2
        elif t == "paragraph_open" and tok.map:
            block = add_block("paragraph", tok.map, t, heading_path())
            add_statements(block, tok.map, heading=False, split=True)
            if i + 1 < n:
                collect_links(tokens[i + 1])
            i += 2
        elif t in ("fence", "code_block") and tok.map:
            block = add_block("code_fence", tok.map, t, heading_path())
            language = tok.info.split()[0] if tok.info and tok.info.strip() else None
            code_blocks.append(
                CodeBlockRef(
                    path=path,
                    language=language,
                    line=block.line,
                    end_line=block.end_line,
                    identifiers=_identifiers(tok.content, language),
                    content_len=len(tok.content),
                )
            )
        elif t == "table_open" and tok.map:
            i = _handle_table(
                tokens,
                i,
                path,
                lines,
                text,
                starts,
                heading_path(),
                add_block,
                statements,
                tables,
                collect_links,
            )
            continue
        i += 1

    for label, ref in sorted(env.get("references", {}).items()):
        href = str(ref.get("href", ""))
        kind, resolved = classify_link(path, href)
        ref_map = ref.get("map") or [0, 1]
        links.append(
            DocLink(
                path=path,
                text=str(label),
                target=href,
                line=ref_map[0] + 1,
                kind=kind,
                resolved_path=resolved,
            )
        )

    return ParsedDocument(
        path=path,
        commit_sha=commit_sha,
        blocks=tuple(blocks),
        statements=tuple(statements),
        tables=tuple(tables),
        code_blocks=tuple(code_blocks),
        links=tuple(links),
        errors=tuple(errors),
    )


def _handle_table(
    tokens: list[Token],
    start: int,
    path: str,
    lines: list[str],
    text: str,
    starts: list[int],
    hp: tuple[str, ...],
    add_block: Any,
    statements: list[DocStatement],
    tables: list[DocTable],
    collect_links: Any,
) -> int:
    n = len(tokens)
    table_tok = tokens[start]
    header: list[str] = []
    rows: list[list[TableCellRef]] = []
    in_head = False
    i = start + 1
    while i < n and tokens[i].type != "table_close":
        tok = tokens[i]
        if tok.type == "thead_open":
            in_head = True
        elif tok.type == "thead_close":
            in_head = False
        elif tok.type == "tr_open" and tok.map:
            line_idx = tok.map[0]
            line_text = lines[line_idx].rstrip("\r\n") if line_idx < len(lines) else ""
            raw_cells = _split_row(line_text)
            j = i + 1
            col = 0
            tok_cells: list[str] = []
            while j < n and tokens[j].type != "tr_close":
                if tokens[j].type == "inline":
                    tok_cells.append(tokens[j].content)
                    collect_links(tokens[j])
                j += 1
            block = add_block("table_row", [line_idx, line_idx + 1], "tr_open", hp)
            if in_head:
                header = [c.replace("\\|", "|") for c in raw_cells] or tok_cells
            else:
                refs: list[TableCellRef] = []
                for col in range(len(raw_cells)):
                    raw_cell = raw_cells[col]
                    verified = bool(raw_cell) and raw_cell in line_text
                    refs.append(
                        TableCellRef(
                            row=len(rows),
                            col=col,
                            text=raw_cell.replace("\\|", "|"),
                            line=line_idx + 1,
                            line_verified=verified,
                        )
                    )
                rows.append(refs)
            line_start = starts[line_idx] if line_idx < len(starts) else len(text)
            stripped = line_text.strip()
            lead = len(line_text) - len(line_text.lstrip())
            if stripped:
                statements.append(
                    DocStatement(
                        statement_id=_hash(block.block_id, 0),
                        block_id=block.block_id,
                        path=path,
                        text=normalize_ws(stripped),
                        raw_start=line_start + lead,
                        raw_end=line_start + lead + len(stripped),
                        line=line_idx + 1,
                        column=lead,
                        end_line=line_idx + 1,
                        location_verified=text[
                            line_start + lead : line_start + lead + len(stripped)
                        ]
                        == stripped,
                        heading_path=hp,
                    )
                )
            i = j
        i += 1
    assert table_tok.map is not None
    tables.append(
        DocTable(
            path=path,
            header=tuple(header),
            rows=tuple(tuple(r) for r in rows),
            line=table_tok.map[0] + 1,
        )
    )
    return i + 1
