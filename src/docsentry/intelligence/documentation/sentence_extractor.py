"""Mask-then-slice sentence splitting with exact character offsets."""

import re
from dataclasses import dataclass

_LINE_PREFIX = re.compile(r"^([ \t]*>)+[ \t]?")
_LIST_MARKER = re.compile(r"^[ \t]*([-*+]|\d+[.)])[ \t]+")
_HEADING_PREFIX = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+")
_HEADING_SUFFIX = re.compile(r"[ \t]+#+[ \t]*$")
_SETEXT = re.compile(r"^[ \t]*(=+|-+)[ \t]*$")

_PROTECTED = [
    re.compile(r"(`+)(?:.+?)\1", re.DOTALL),
    re.compile(r"\]\([^)\n]*\)"),
    re.compile(r"\]\[[^\]\n]*\]"),
    re.compile(r"https?://[^\s<>)\]]+[^\s<>)\].,;:!?]"),
    re.compile(r"\d+[.,]\d+"),
    re.compile(r"\b(?:e\.g\.|i\.e\.|etc\.|vs\.|approx\.|Dr\.|Mr\.|Mrs\.|No\.)"),
    re.compile(
        r"[\w\-/]+\.(?:py|md|json|toml|ya?ml|txt|cfg|ini|env|js|ts|rst|sh|lock)\b",
    ),
    re.compile(r"\b\w+(?:\.\w+){2,}\b"),
]

_BOUNDARY = re.compile(
    r"(?<=[.!?])(?P<q>[\"')\]]*)\s+(?=[A-Z0-9`\"'(\[\x00])|(?P<blank>\n[ \t]*\n)"
)

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class SentenceSpan:
    text: str
    start: int  # offset inside block_text
    end: int
    line: int
    column: int
    end_line: int
    verified: bool


def normalize_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def neutralize(block_text: str, *, heading: bool = False) -> str:
    """Same-length copy with markdown prefixes replaced by spaces."""
    lines = block_text.split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        work = line
        m = _LINE_PREFIX.match(work)
        if m:
            work = " " * m.end() + work[m.end() :]
        if i == 0:
            m = _LIST_MARKER.match(work)
            if m:
                work = " " * m.end() + work[m.end() :]
            if heading:
                m = _HEADING_PREFIX.match(work)
                if m:
                    work = " " * m.end() + work[m.end() :]
                m2 = _HEADING_SUFFIX.search(work)
                if m2:
                    work = work[: m2.start()] + " " * (len(work) - m2.start())
        elif heading and _SETEXT.match(work):
            work = " " * len(work)
        out.append(work)
    return "\n".join(out)


def mask_protected(text: str) -> str:
    chars = list(text)
    for pattern in _PROTECTED:
        for m in pattern.finditer("".join(chars)):
            for i in range(m.start(), m.end()):
                chars[i] = "\x00"
    return "".join(chars)


def _locate(block_text: str, start: int, block_start_line: int) -> tuple[int, int]:
    before = block_text[:start]
    line = block_start_line + before.count("\n")
    column = start - (before.rfind("\n") + 1)
    return line, column


def split_sentences(
    block_text: str,
    block_start_offset: int,
    block_start_line: int,
    *,
    file_text: str | None = None,
    heading: bool = False,
    split: bool = True,
) -> list[SentenceSpan]:
    working = neutralize(block_text, heading=heading)
    masked = mask_protected(working)
    segments: list[tuple[int, int]] = []
    if split:
        pos = 0
        for m in _BOUNDARY.finditer(masked):
            end = m.start() if m.group("blank") else m.start() + len(m.group("q"))
            segments.append((pos, end))
            pos = m.end()
        segments.append((pos, len(masked)))
    else:
        segments.append((0, len(masked)))

    spans: list[SentenceSpan] = []
    for start, end in segments:
        while start < end and working[start].isspace():
            start += 1
        while end > start and working[end - 1].isspace():
            end -= 1
        if start >= end:
            continue
        raw = block_text[start:end]
        text = normalize_ws(raw)
        if not text:
            continue
        line, column = _locate(block_text, start, block_start_line)
        end_line = block_start_line + block_text[:end].count("\n")
        verified = True
        if file_text is not None:
            a = block_start_offset + start
            b = block_start_offset + end
            verified = normalize_ws(file_text[a:b]) == text
        spans.append(SentenceSpan(text, start, end, line, column, end_line, verified))
    return spans
