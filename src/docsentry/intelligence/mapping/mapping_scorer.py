"""Signal scoring for a (claim, entity) pair."""

import posixpath
import re
from dataclasses import dataclass

from docsentry.intelligence.mapping.candidate_retriever import (
    name_tokens,
    symbol_from_text,
    ticked_symbols,
)
from docsentry.intelligence.models.code import CodeEntity
from docsentry.intelligence.models.common import Provenance, Strength
from docsentry.intelligence.models.documentation import DocClaim, DocLink
from docsentry.intelligence.models.relationships import MappingSignal, SignalKind

WEIGHTS = {Strength.STRONG: 3.0, Strength.MEDIUM: 1.5, Strength.WEAK: 0.5}
_PATH_MENTION = re.compile(r"[\w./\-]+\.py\b")
_GENERIC_PATH_WORDS = frozenset(
    {"docs", "doc", "src", "readme", "index", "md", "py", "init", "main", "guide", "lib", "app"}
)
_STEM_SUFFIXES = ("ing", "ed", "es", "s")


@dataclass(frozen=True)
class ClaimContext:
    claim: DocClaim
    block_text: str
    links: tuple[DocLink, ...]
    commit_sha: str


def _stem(token: str) -> str:
    t = token.lower()
    if len(t) > 3 and t.endswith("e"):
        t = t[:-1]
    for suffix in _STEM_SUFFIXES:
        if len(t) > len(suffix) + 2 and t.endswith(suffix):
            return t[: -len(suffix)]
    return t


def _prov(ctx: ClaimContext) -> Provenance:
    c = ctx.claim
    return Provenance(
        path=c.path, commit_sha=ctx.commit_sha, line=c.line, snippet=c.original_text[:120]
    )


def _heading_symbol(claim: DocClaim) -> tuple[str, str] | None:
    if not claim.heading_path:
        return None
    raw = claim.heading_path[-1]
    return raw, symbol_from_text(raw)


def _path_words(path: str) -> set[str]:
    words: set[str] = set()
    for part in re.split(r"[/._\-]+", path.lower()):
        if part and part not in _GENERIC_PATH_WORDS and len(part) > 2:
            words.add(part)
    return words


def _words_related(a: set[str], b: set[str]) -> bool:
    for x in a:
        for y in b:
            if x == y or (min(len(x), len(y)) >= 4 and (x.startswith(y) or y.startswith(x))):
                return True
    return False


def score_entity(ctx: ClaimContext, entity: CodeEntity) -> list[MappingSignal]:
    claim = ctx.claim
    signals: list[MappingSignal] = []
    prov = _prov(ctx)
    ticked = ticked_symbols(claim.original_text)

    # A: explicit reference (relative link, path mention, anchor)
    explicit: str | None = None
    for link in ctx.links:
        if link.kind == "relative_path" and link.resolved_path == entity.path:
            explicit = f"link to {entity.path}"
        elif link.kind == "anchor":
            slug = link.target.lstrip("#").replace("-", "_").lower()
            if slug == entity.name.lower():
                explicit = f"anchor to {entity.name}"
    if explicit is None:
        for mention in _PATH_MENTION.findall(claim.original_text + " " + ctx.block_text):
            norm = posixpath.normpath(mention)
            if entity.path == norm or entity.path.endswith("/" + norm):
                explicit = f"path mention {mention}"
                break
    if explicit:
        signals.append(
            MappingSignal(
                kind=SignalKind.EXPLICIT_REFERENCE,
                tier=Strength.STRONG,
                detail=explicit,
                evidence=prov,
            )
        )

    # B: exact identifier (case-sensitive)
    names = [claim.subject, *claim.parameters, *ticked]
    exact: str | None = None
    for n in names:
        if not n:
            continue
        if n == entity.name or n == entity.qualname:
            exact = n
        elif "." in n and entity.qualname.endswith(".".join(n.split(".")[-2:])):
            exact = n
        if exact:
            break
    if exact:
        signals.append(
            MappingSignal(
                kind=SignalKind.EXACT_IDENTIFIER,
                tier=Strength.STRONG,
                detail=f"identifier {exact}",
                evidence=prov,
            )
        )

    # C: heading symbol
    heading = _heading_symbol(claim)
    heading_strong = False
    if heading is not None:
        raw, sym = heading
        if sym == entity.name or sym == entity.qualname:
            heading_strong = True
            signals.append(
                MappingSignal(
                    kind=SignalKind.HEADING_SYMBOL,
                    tier=Strength.STRONG,
                    detail=f"heading is exactly {entity.name}",
                    evidence=prov,
                )
            )
        elif re.search(rf"(?<![\w]){re.escape(entity.name)}(?![\w])", raw):
            signals.append(
                MappingSignal(
                    kind=SignalKind.HEADING_SYMBOL,
                    tier=Strength.MEDIUM,
                    detail=f"heading mentions {entity.name}",
                    evidence=prov,
                )
            )

    # D: config / parameter name
    if claim.subject:
        param_names = {p.name for p in entity.parameters}
        if claim.subject in param_names:
            tier = Strength.STRONG if heading_strong else Strength.MEDIUM
            signals.append(
                MappingSignal(
                    kind=SignalKind.CONFIG_OR_PARAMETER_NAME,
                    tier=tier,
                    detail=f"parameter {claim.subject}",
                    evidence=prov,
                )
            )
        elif claim.subject_tokens and set(claim.subject_tokens) <= {
            t for t in name_tokens(entity.name)
        }:
            signals.append(
                MappingSignal(
                    kind=SignalKind.CONFIG_OR_PARAMETER_NAME,
                    tier=Strength.MEDIUM,
                    detail=f"subject tokens in {entity.name}",
                    evidence=prov,
                )
            )

    # F: contextual
    if heading is not None:
        h_tokens = {_stem(t) for w in re.split(r"\W+", heading[0]) for t in name_tokens(w) if t}
        e_tokens = {_stem(t) for t in name_tokens(entity.name)}
        shared = h_tokens & e_tokens
        if len(shared) >= 2:
            signals.append(
                MappingSignal(
                    kind=SignalKind.CONTEXTUAL,
                    tier=Strength.MEDIUM,
                    detail="shared heading words: " + ",".join(sorted(shared)),
                    evidence=prov,
                )
            )
        elif shared:
            signals.append(
                MappingSignal(
                    kind=SignalKind.CONTEXTUAL,
                    tier=Strength.WEAK,
                    detail="shared heading word: " + ",".join(sorted(shared)),
                    evidence=prov,
                )
            )
    nearby = [s for s in ticked_symbols(ctx.block_text) if s == entity.name]
    if nearby and not exact:
        signals.append(
            MappingSignal(
                kind=SignalKind.CONTEXTUAL,
                tier=Strength.MEDIUM,
                detail=f"nearby identifier {entity.name}",
                evidence=prov,
            )
        )

    # G: file proximity
    if _words_related(_path_words(claim.path), _path_words(entity.path)):
        signals.append(
            MappingSignal(
                kind=SignalKind.FILE_PROXIMITY,
                tier=Strength.WEAK,
                detail=f"{claim.path} ~ {entity.path}",
                evidence=prov,
            )
        )
    return signals


def strength_of(signals: list[MappingSignal]) -> Strength:
    tiers = {s.tier for s in signals}
    if Strength.STRONG in tiers:
        return Strength.STRONG
    if Strength.MEDIUM in tiers:
        return Strength.MEDIUM
    return Strength.WEAK


def rank_of(signals: list[MappingSignal]) -> float:
    return sum(WEIGHTS[s.tier] for s in signals)
