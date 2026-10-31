"""Semantic diff between matched entities."""

import hashlib
import re
from typing import Any

from docsentry.intelligence.change_analysis.entity_matcher import MatchResult
from docsentry.intelligence.models.changes import ChangedProperty, ChangeType, SemanticChange
from docsentry.intelligence.models.code import CodeEntity, Parameter
from docsentry.intelligence.models.common import Strength, ValueRepr


def _norm_expr(expr: str) -> str:
    return re.sub(r"\s+", "", expr)


def _value_differs(a: ValueRepr | None, b: ValueRepr | None) -> tuple[bool, bool]:
    """Return (differs, unresolved_comparison)."""
    if a is None and b is None:
        return False, False
    if a is None or b is None:
        return True, False
    if a.resolved and b.resolved:
        return a.value != b.value or type(a.value) is not type(b.value), False
    return _norm_expr(a.source_expr) != _norm_expr(b.source_expr), True


def _show(v: ValueRepr | None) -> Any:
    if v is None:
        return None
    return v.value if v.resolved else v.source_expr


def _cid(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def _change(
    base: CodeEntity | None,
    head: CodeEntity | None,
    ctype: ChangeType,
    prop: ChangedProperty,
    *,
    detail: str | None = None,
    before: Any = None,
    after: Any = None,
    evidence: tuple[str, ...] = (),
    confidence: Strength | None = None,
) -> SemanticChange:
    anchor = head or base
    assert anchor is not None
    return SemanticChange(
        change_id=_cid(
            base.symbol_key if base else "", head.symbol_key if head else "", ctype, prop, detail
        ),
        entity_id=anchor.id,
        base_entity_id=base.id if base else None,
        symbol_key=anchor.symbol_key,
        base_symbol_key=base.symbol_key if base else None,
        entity_name=anchor.name,
        change_type=ctype,
        property=prop,
        detail=detail,
        before=before,
        after=after,
        base_provenance=base.provenance if base else None,
        head_provenance=head.provenance if head else None,
        evidence=evidence,
        rename_confidence=confidence,
        exposure=anchor.exposure,
    )


def _via(v: ValueRepr | None) -> str | None:
    return v.resolved_via if v is not None and v.resolved_via else None


def _diff_pair(base: CodeEntity, head: CodeEntity, ctype: ChangeType) -> list[SemanticChange]:
    out: list[SemanticChange] = []
    if base.kind != head.kind:
        out.append(
            _change(
                base, head, ChangeType.MODIFIED, ChangedProperty.SIGNATURE_OTHER,
                detail="kind", before=base.kind, after=head.kind,
                evidence=(f"kind changed from {base.kind} to {head.kind}",),
            )
        )  # fmt: skip
        return out

    if base.exposure != head.exposure:
        out.append(
            _change(
                base, head, ChangeType.MODIFIED, ChangedProperty.EXPOSURE,
                before=base.exposure.value, after=head.exposure.value,
                evidence=(f"exposure changed from {base.exposure} to {head.exposure}",),
            )
        )  # fmt: skip

    if base.kind in ("function", "method"):
        out.extend(_diff_callable(base, head))
    elif base.kind in ("constant", "class_variable", "config_key"):
        differs, unresolved = _value_differs(base.value, head.value)
        if differs:
            prop = (
                ChangedProperty.CONFIG_DEFAULT
                if head.kind == "config_key"
                else ChangedProperty.CONSTANT_VALUE
            )
            ev = [f"value changed from {_show(base.value)!r} to {_show(head.value)!r}"]
            if unresolved:
                ev.append("unresolved")
            out.append(
                _change(
                    base, head, ChangeType.MODIFIED, prop,
                    before=_show(base.value), after=_show(head.value), evidence=tuple(ev),
                )
            )  # fmt: skip
    return out


def _diff_callable(base: CodeEntity, head: CodeEntity) -> list[SemanticChange]:
    out: list[SemanticChange] = []
    bp: dict[str, Parameter] = {p.name: p for p in base.parameters}
    hp: dict[str, Parameter] = {p.name: p for p in head.parameters}
    for name in sorted(set(bp) - set(hp)):
        out.append(
            _change(
                base, head, ChangeType.MODIFIED, ChangedProperty.PARAMETER_REMOVED,
                detail=name, before=name, evidence=(f"parameter '{name}' removed",),
            )
        )  # fmt: skip
    for name in sorted(set(hp) - set(bp)):
        out.append(
            _change(
                base, head, ChangeType.MODIFIED, ChangedProperty.PARAMETER_ADDED,
                detail=name, after=name, evidence=(f"parameter '{name}' added",),
            )
        )  # fmt: skip
    for name in sorted(set(bp) & set(hp)):
        b, h = bp[name], hp[name]
        differs, unresolved = _value_differs(b.default, h.default)
        if differs:
            ev = [f"default of '{name}' changed from {_show(b.default)!r} to {_show(h.default)!r}"]
            via = _via(h.default) or _via(b.default)
            if via:
                ev.append(f"via constant {via}")
            if unresolved:
                ev.append("unresolved")
            out.append(
                _change(
                    base, head, ChangeType.MODIFIED, ChangedProperty.DEFAULT_VALUE,
                    detail=name, before=_show(b.default), after=_show(h.default),
                    evidence=tuple(ev),
                )
            )  # fmt: skip
        if b.annotation != h.annotation:
            out.append(
                _change(
                    base, head, ChangeType.MODIFIED, ChangedProperty.PARAMETER_TYPE,
                    detail=name, before=b.annotation, after=h.annotation,
                    evidence=(f"annotation of '{name}' changed",),
                )
            )  # fmt: skip
        if b.kind != h.kind:
            out.append(
                _change(
                    base, head, ChangeType.MODIFIED, ChangedProperty.SIGNATURE_OTHER,
                    detail=f"kind:{name}", before=b.kind, after=h.kind,
                    evidence=(f"kind of '{name}' changed",),
                )
            )  # fmt: skip
    if base.return_annotation != head.return_annotation:
        out.append(
            _change(
                base, head, ChangeType.MODIFIED, ChangedProperty.RETURN_TYPE,
                before=base.return_annotation, after=head.return_annotation,
                evidence=("return annotation changed",),
            )
        )  # fmt: skip
    if base.is_async != head.is_async:
        out.append(
            _change(
                base, head, ChangeType.MODIFIED, ChangedProperty.SIGNATURE_OTHER,
                detail="async", before=base.is_async, after=head.is_async,
                evidence=("async-ness changed",),
            )
        )  # fmt: skip
    return out


def diff_entities(match: MatchResult) -> list[SemanticChange]:
    changes: list[SemanticChange] = []
    for e in match.added:
        changes.append(
            _change(None, e, ChangeType.ADDED, ChangedProperty.ENTITY, after=e.name,
                    evidence=(f"{e.kind} '{e.qualname}' added",))
        )  # fmt: skip
    for e in match.removed:
        changes.append(
            _change(e, None, ChangeType.REMOVED, ChangedProperty.ENTITY, before=e.name,
                    evidence=(f"{e.kind} '{e.qualname}' removed",))
        )  # fmt: skip
    for pair in match.renames:
        changes.append(
            _change(
                pair.base, pair.head, ChangeType.RENAMED, ChangedProperty.ENTITY,
                before=pair.base.name, after=pair.head.name, confidence=pair.confidence,
                evidence=(f"{pair.base.name} -> {pair.head.name}",),
            )
        )  # fmt: skip
        changes.extend(_diff_pair(pair.base, pair.head, ChangeType.RENAMED))
    for amb in match.ambiguous:
        _ = amb  # ambiguous candidates remain removed + added; kept in MatchResult for Stage 4
    for b, h in match.matched:
        if b.path != h.path:
            changes.append(
                _change(
                    b, h, ChangeType.MOVED, ChangedProperty.ENTITY,
                    before=b.path, after=h.path, evidence=(f"moved from {b.path} to {h.path}",),
                )
            )  # fmt: skip
        changes.extend(_diff_pair(b, h, ChangeType.MODIFIED))
    return sorted(
        changes,
        key=lambda c: (
            c.symbol_key,
            c.change_type.value,
            c.property.value,
            c.detail or "",
            c.change_id,
        ),
    )
