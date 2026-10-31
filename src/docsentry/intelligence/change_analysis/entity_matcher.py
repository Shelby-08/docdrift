"""Conservative entity matching between base and head."""

import difflib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from docsentry.intelligence.models.code import CodeEntity
from docsentry.intelligence.models.common import Strength


@dataclass(frozen=True)
class RenamePair:
    base: CodeEntity
    head: CodeEntity
    confidence: Strength
    score: float


@dataclass(frozen=True)
class AmbiguousRename:
    base_ids: tuple[str, ...]
    head_ids: tuple[str, ...]
    note: str


@dataclass
class MatchResult:
    matched: list[tuple[CodeEntity, CodeEntity]] = field(default_factory=list)
    added: list[CodeEntity] = field(default_factory=list)
    removed: list[CodeEntity] = field(default_factory=list)
    renames: list[RenamePair] = field(default_factory=list)
    ambiguous: list[AmbiguousRename] = field(default_factory=list)


def mapped_key(entity: CodeEntity, file_renames: Mapping[str, str]) -> str:
    return f"{file_renames.get(entity.path, entity.path)}::{entity.qualname}"


def _container(entity: CodeEntity, file_renames: Mapping[str, str]) -> tuple[str, str]:
    path = file_renames.get(entity.path, entity.path)
    parent = entity.qualname.rsplit(".", 1)[0] if "." in entity.qualname else ""
    return path, parent


def _stem(token: str) -> str:
    t = token.lower()
    if len(t) > 3 and t.endswith("e"):
        t = t[:-1]
    for suffix in ("ing", "ed", "es", "s"):
        if len(t) > len(suffix) + 2 and t.endswith(suffix):
            return t[: -len(suffix)]
    return t


def _tokens(name: str) -> set[str]:
    parts = re.split(r"_+|(?<=[a-z0-9])(?=[A-Z])", name)
    return {_stem(p) for p in parts if p}


def _name_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _param_names(entity: CodeEntity) -> list[str]:
    return [p.name for p in entity.parameters]


def _pair_score(base: CodeEntity, head: CodeEntity) -> float | None:
    if base.kind != head.kind:
        return None
    ratio = _name_ratio(base.name, head.name)
    if base.kind in ("function", "method"):
        bp, hp = _param_names(base), _param_names(head)
        same = bp == hp or (
            len(bp) == len(hp) and _jaccard(set(bp), set(hp)) >= 0.8 and len(bp) > 0
        )
        if not same or ratio < 0.6:
            return None
        return ratio + (1.0 if bp == hp else 0.5)
    if base.kind in ("constant", "class_variable", "config_key"):
        bv, hv = base.value, head.value
        if bv is None or hv is None or not bv.resolved or not hv.resolved or bv.value != hv.value:
            return None
        jac = _jaccard(_tokens(base.name), _tokens(head.name))
        if jac < 0.5 and ratio < 0.6:
            return None
        return max(jac, ratio) + 1.0
    if base.kind == "class":
        if base.bases != head.bases or ratio < 0.6:
            return None
        return ratio + 0.5
    return None


def match_entities(
    base_entities: Sequence[CodeEntity],
    head_entities: Sequence[CodeEntity],
    file_renames: Mapping[str, str],
) -> MatchResult:
    result = MatchResult()
    head_by_key = {e.symbol_key: e for e in head_entities}
    used_heads: set[str] = set()
    left_base: list[CodeEntity] = []
    for b in sorted(base_entities, key=lambda e: (e.path, e.qualname, e.id)):
        h = head_by_key.get(mapped_key(b, file_renames))
        if h is not None and h.symbol_key not in used_heads:
            used_heads.add(h.symbol_key)
            result.matched.append((b, h))
        else:
            left_base.append(b)
    left_head = sorted(
        (e for e in head_entities if e.symbol_key not in used_heads),
        key=lambda e: (e.path, e.qualname, e.id),
    )

    scores: dict[tuple[str, str], float] = {}
    for b in left_base:
        for h in left_head:
            if _container(b, file_renames) != _container(h, {}):
                continue
            s = _pair_score(b, h)
            if s is not None:
                scores[(b.id, h.id)] = s

    base_by_id = {e.id: e for e in left_base}
    head_by_id = {e.id: e for e in left_head}
    best_b: dict[str, list[str]] = {}
    best_h: dict[str, list[str]] = {}
    for b in left_base:
        cands = {h: s for (bi, h), s in scores.items() if bi == b.id}
        if cands:
            top = max(cands.values())
            best_b[b.id] = sorted(h for h, s in cands.items() if s == top)
    for h in left_head:
        cands_h = {bi: s for (bi, hi), s in scores.items() if hi == h.id}
        if cands_h:
            top = max(cands_h.values())
            best_h[h.id] = sorted(bi for bi, s in cands_h.items() if s == top)

    renamed_b: set[str] = set()
    renamed_h: set[str] = set()
    for bid, hs in sorted(best_b.items()):
        if len(hs) == 1 and best_h.get(hs[0]) == [bid] and not _competing(scores, bid, hs[0]):
            b, h = base_by_id[bid], head_by_id[hs[0]]
            sc = scores[(bid, hs[0])]
            conf = Strength.STRONG if sc >= 1.8 else Strength.MEDIUM
            result.renames.append(RenamePair(b, h, conf, sc))
            renamed_b.add(bid)
            renamed_h.add(hs[0])
        else:
            heads = sorted({h for (bi, h) in scores if bi == bid})
            result.ambiguous.append(
                AmbiguousRename(
                    (bid,), tuple(heads), "multiple rename candidates; kept as removed+added"
                )
            )
    result.removed = [e for e in left_base if e.id not in renamed_b]
    result.added = [e for e in left_head if e.id not in renamed_h]
    return result


def _competing(scores: dict[tuple[str, str], float], bid: str, hid: str) -> bool:
    """True when another eligible pair shares either side with a different partner."""
    return any((bi == bid) != (hi == hid) for (bi, hi) in scores if bi == bid or hi == hid)
