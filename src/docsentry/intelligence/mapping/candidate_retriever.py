"""Deterministic token-index candidate retrieval (no semantic search)."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from docsentry.intelligence.models.code import CodeEntity
from docsentry.intelligence.models.common import AnalysisLimits
from docsentry.intelligence.models.documentation import DocClaim

_TICKED = re.compile(r"`([^`\n]+)`")
_SPLIT = re.compile(r"_+|(?<=[a-z0-9])(?=[A-Z])")
_NON_SYMBOL = frozenset(
    {"the", "a", "an", "default", "value", "of", "is", "for", "option", "setting"}
)


def name_tokens(name: str) -> tuple[str, ...]:
    return tuple(t.lower() for t in _SPLIT.split(name) if t)


def symbol_from_text(text: str) -> str:
    """Strip backticks, call parens and trailing punctuation from a symbol-like text."""
    t = text.strip().strip("`").strip()
    if "(" in t and t.endswith(")"):
        t = t.split("(", 1)[0].strip()
    elif t.endswith("()"):
        t = t[:-2]
    return t.strip()


def ticked_symbols(text: str) -> list[str]:
    out: list[str] = []
    for m in _TICKED.finditer(text):
        sym = symbol_from_text(m.group(1))
        sym = sym.split("(")[0]
        if re.fullmatch(r"[A-Za-z_][\w.]*", sym):
            out.append(sym)
    return out


@dataclass
class CandidateIndex:
    entities: dict[str, CodeEntity] = field(default_factory=dict)
    by_name: dict[str, list[str]] = field(default_factory=dict)
    by_token: dict[str, set[str]] = field(default_factory=dict)
    by_param: dict[str, list[str]] = field(default_factory=dict)


def build_candidate_index(entities: Iterable[CodeEntity]) -> CandidateIndex:
    idx = CandidateIndex()
    for e in entities:
        idx.entities[e.id] = e
        idx.by_name.setdefault(e.name, []).append(e.id)
        tokens = set(name_tokens(e.name))
        for part in e.qualname.split("."):
            tokens.update(name_tokens(part))
        for tok in tokens:
            idx.by_token.setdefault(tok, set()).add(e.id)
        for p in e.parameters:
            idx.by_param.setdefault(p.name, []).append(e.id)
    return idx


def claim_names(claim: DocClaim) -> list[str]:
    names: list[str] = []
    if claim.subject:
        names.append(claim.subject)
    names.extend(claim.parameters)
    names.extend(ticked_symbols(claim.original_text))
    if claim.heading_path:
        head = symbol_from_text(claim.heading_path[-1])
        if re.fullmatch(r"[A-Za-z_][\w.]*", head):
            names.append(head)
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def retrieve_candidates(
    claim: DocClaim, index: CandidateIndex, limits: AnalysisLimits
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def push(ids: Iterable[str]) -> None:
        for eid in sorted(ids, key=lambda i: (index.entities[i].symbol_key, i)):
            if eid not in seen:
                seen.add(eid)
                ordered.append(eid)

    names = claim_names(claim)
    for name in names:
        last = name.split(".")[-1]
        exact = set(index.by_name.get(last, []))
        if "." in name:
            exact = {
                i
                for i in exact
                if index.entities[i].qualname.endswith(".".join(name.split(".")[-2:]))
            } or exact
        push(exact)
    if claim.subject:
        push(set(index.by_param.get(claim.subject, [])))
    tokens = [t for t in claim.subject_tokens if t not in _NON_SYMBOL]
    if tokens:
        sets = [index.by_token.get(t, set()) for t in tokens]
        push(set.intersection(*sets) if sets else set())
        push(set.union(*sets) if sets else set())
    return ordered[: limits.max_candidates_per_claim]


def all_candidate_ids(
    claims: Sequence[DocClaim], index: CandidateIndex, limits: AnalysisLimits
) -> set[str]:
    out: set[str] = set()
    for c in claims:
        out.update(retrieve_candidates(c, index, limits))
    return out
