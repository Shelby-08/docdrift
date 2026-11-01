"""Deterministic drift rules R1-R4, evaluated on ONE side (base or head)."""

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence

from docsentry.intelligence.code_analysis.symbol_index import SymbolIndex
from docsentry.intelligence.code_analysis.value_extractor import extract_unit_hint
from docsentry.intelligence.documentation.claim_extractor import HINT_TO_LABEL, UNIT_SECONDS
from docsentry.intelligence.models.code import CodeEntity, CodeFact
from docsentry.intelligence.models.common import (
    ConsistencyState,
    Exposure,
    Provenance,
    Side,
    Strength,
    ValueRepr,
)
from docsentry.intelligence.models.documentation import ClaimType, DocClaim
from docsentry.intelligence.models.findings import (
    Category,
    ConsistencyRecord,
    Evidence,
    EvidenceStatus,
)
from docsentry.intelligence.models.relationships import Relationship, SignalKind

_SENTINEL_AMBIGUOUS = "ambiguous"


def claim_identities(claims: Sequence[DocClaim], doc_path: Callable[[str], str]) -> dict[str, str]:
    """Stable claim identity that EXCLUDES the claim value."""
    counter: Counter[tuple[str, str, str, str]] = Counter()
    out: dict[str, str] = {}
    for c in sorted(claims, key=lambda c: (c.path, c.line, c.claim_id)):
        subject = (c.subject or "").strip().lower()
        heading = re.sub(r"\s+", " ", c.heading_path[-1]).strip().lower() if c.heading_path else ""
        base = (doc_path(c.path), c.claim_type.value, subject, heading)
        occ = counter[base]
        counter[base] += 1
        out[c.claim_id] = "~".join([*base, str(occ)])
    return out


def _numeric(vr: ValueRepr | None) -> float | None:
    if vr is None or not vr.resolved:
        return None
    v = vr.value
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str) and re.fullmatch(r"\d+(?:\.\d+)?", v.strip()):
        return float(v.strip())
    return None


def _claim_prov(claim: DocClaim, sha: str) -> Provenance:
    return Provenance(
        path=claim.path, commit_sha=sha, line=claim.line, snippet=claim.original_text[:120]
    )


def _mapping_evidence(side: Side, rel: Relationship) -> list[Evidence]:
    return [
        Evidence(kind="mapping_signal", side=side, description=s.detail, provenance=s.evidence)
        for s in rel.signals[:4]
    ]


class RuleContext:
    def __init__(
        self,
        side: Side,
        claims: Sequence[DocClaim],
        entities: Sequence[CodeEntity],
        facts: Sequence[CodeFact],
        relationships: Sequence[Relationship],
        symbol_index: SymbolIndex,
        snapshot_complete: bool,
        *,
        doc_sha: str,
        base_index: SymbolIndex | None,
        rename_candidates: Mapping[str, str],
        entity_key: Callable[[CodeEntity], str],
        doc_path: Callable[[str], str],
    ) -> None:
        self.side = side
        self.claims = claims
        self.entities = entities
        self.facts = facts
        self.symbol_index = symbol_index
        self.snapshot_complete = snapshot_complete
        self.doc_sha = doc_sha
        self.base_index = base_index
        self.rename_candidates = rename_candidates
        self.entity_key = entity_key
        self.by_id = {e.id: e for e in entities}
        self.identities = claim_identities(claims, doc_path)
        rels: dict[str, list[Relationship]] = {}
        for r in relationships:
            rels.setdefault(r.claim_id, []).append(r)
        for lst in rels.values():
            lst.sort(key=lambda r: (-r.rank_score, r.relationship_id))
        self.rels = rels
        self.out: dict[str, ConsistencyRecord] = {}

    def key(self, rule: str, claim: DocClaim, entity_identity: str, prop: str) -> str:
        return "|".join([rule, self.identities[claim.claim_id], entity_identity, prop])

    def add(self, rec: ConsistencyRecord) -> None:
        self.out.setdefault(rec.key, rec)


def _unit_hint_for(ctx: RuleContext, entity: CodeEntity, prop_name: str | None) -> str | None:
    for f in ctx.facts:
        if (
            f.entity_id == entity.id
            and f.unit_hint
            and (f.property == prop_name or prop_name is None)
        ):
            return f.unit_hint
    if prop_name:
        return extract_unit_hint(prop_name) or extract_unit_hint(entity.name)
    return extract_unit_hint(entity.name)


def _value_target(claim: DocClaim, entity: CodeEntity) -> tuple[str, ValueRepr, str | None] | None:
    if entity.kind in ("constant", "config_key", "class_variable") and entity.value is not None:
        return "value", entity.value, None
    if entity.kind in ("function", "method"):
        for p in entity.parameters:
            if p.default is not None and claim.subject and p.name == claim.subject:
                return f"parameter_default:{p.name}", p.default, p.name
    return None


def _severity_exposure(entity: CodeEntity | None) -> Exposure:
    return entity.exposure if entity else Exposure.UNKNOWN


def _rule_r1(ctx: RuleContext) -> None:
    for claim in ctx.claims:
        if claim.claim_type != ClaimType.CONFIGURATION_DEFAULT:
            continue
        if isinstance(claim.value, bool) or not isinstance(claim.value, int | float):
            continue
        rels = ctx.rels.get(claim.claim_id, [])
        if not rels:
            continue
        cprov = _claim_prov(claim, ctx.doc_sha)
        doc_ev = Evidence(
            kind="doc_claim", side=ctx.side, description=claim.original_text[:200], provenance=cprov
        )
        if rels[0].ambiguous:
            rel = rels[0]
            ctx.add(
                ConsistencyRecord(
                    key=ctx.key("R1", claim, _SENTINEL_AMBIGUOUS, "value"),
                    rule_id="R1",
                    category=Category.DEFAULT_VALUE_MISMATCH,
                    state=ConsistencyState.NOT_EVALUABLE,
                    evidence_status=EvidenceStatus.AMBIGUOUS_RELATIONSHIP,
                    claim=claim,
                    property="value",
                    doc_value=claim.value,
                    summary=f"Cannot tell which code entity documents '{claim.subject}'",
                    reasons=("ambiguous_relationship",),
                    mapping_reasons=rel.reasons,
                    evidence=(doc_ev,),
                    requires_ai_review=True,
                )
            )
            continue
        chosen: tuple[Relationship, CodeEntity, str, ValueRepr, str | None] | None = None
        for rel in rels:
            if rel.strength == Strength.WEAK or rel.target_entity_id is None:
                continue
            entity = ctx.by_id.get(rel.target_entity_id)
            if entity is None:
                continue
            target = _value_target(claim, entity)
            if target is not None:
                chosen = (rel, entity, *target)
                break
        if chosen is None:
            continue
        rel, entity, prop, vr, pname = chosen
        identity = ctx.entity_key(entity)
        key = ctx.key("R1", claim, identity, prop)
        code_ev = Evidence(
            kind="code_fact",
            side=ctx.side,
            description=f"{entity.qualname} {prop} = {vr.value if vr.resolved else vr.source_expr}",
            provenance=entity.provenance,
        )
        extra: list[Evidence] = []
        if vr.resolved_via and vr.resolved_via in ctx.by_id:
            via = ctx.by_id[vr.resolved_via]
            extra.append(
                Evidence(
                    kind="code_fact",
                    side=ctx.side,
                    description=f"resolved via constant {via.name}",
                    provenance=via.provenance,
                )
            )
        evidence = (doc_ev, code_ev, *extra, *_mapping_evidence(ctx.side, rel))
        common = {
            "key": key,
            "rule_id": "R1",
            "category": Category.DEFAULT_VALUE_MISMATCH,
            "claim": claim,
            "entity_id": entity.id,
            "entity_name": entity.name,
            "property": prop,
            "doc_value": claim.value,
            "mapping_reasons": rel.reasons,
            "code_provenance": entity.provenance,
            "exposure": _severity_exposure(entity),
        }
        code_num = _numeric(vr)
        if code_num is None:
            ctx.add(
                ConsistencyRecord(
                    **common,
                    state=ConsistencyState.NOT_EVALUABLE,
                    evidence_status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                    code_value=vr.source_expr,
                    summary=f"Code value of {entity.name} could not be resolved statically",
                    reasons=("insufficient_evidence", "code_value_unresolved"),
                    evidence=evidence,
                    requires_ai_review=True,
                )
            )
            continue
        hint = _unit_hint_for(ctx, entity, pname)
        hint_label = HINT_TO_LABEL.get(hint) if hint else None
        reasons: list[str] = []
        units_ok = (claim.unit is None and hint_label is None) or (
            claim.unit is not None and hint_label is not None
        )
        if claim.unit and hint_label:
            doc_cmp = float(claim.value) * UNIT_SECONDS[claim.unit]
            code_cmp = code_num * UNIT_SECONDS[hint_label]
        else:
            doc_cmp, code_cmp = float(claim.value), code_num
            if not units_ok:
                reasons.append("unit_unverified")
        equal = abs(doc_cmp - code_cmp) <= 1e-9 * max(1.0, abs(doc_cmp))
        confirmed = rel.strength == Strength.STRONG and units_ok
        status = EvidenceStatus.CONFIRMED if confirmed else EvidenceStatus.POTENTIAL
        shown = vr.value
        suggest: object = shown
        if claim.unit and hint_label and claim.unit in UNIT_SECONDS:
            converted = code_cmp / UNIT_SECONDS[claim.unit]
            suggest = int(converted) if float(converted).is_integer() else round(converted, 6)
        if equal:
            ctx.add(
                ConsistencyRecord(
                    **common,
                    state=ConsistencyState.CONSISTENT,
                    evidence_status=status,
                    code_value=shown,
                    summary=f"Documented default matches {entity.name}",
                    reasons=tuple(reasons),
                    evidence=evidence,
                )
            )
        else:
            unit_txt = f" {claim.unit}" if claim.unit else ""
            ctx.add(
                ConsistencyRecord(
                    **common,
                    state=ConsistencyState.INCONSISTENT,
                    evidence_status=status,
                    code_value=shown,
                    summary=(
                        f"Documentation says default '{claim.subject}' is {claim.value}{unit_txt}"
                        f" but code has {shown} ({entity.name})"
                    ),
                    reasons=tuple(reasons),
                    evidence=evidence,
                    suggested_correction=(
                        f"Update the documented value {claim.value}{unit_txt} "
                        f"to {suggest}{unit_txt}"
                        if confirmed
                        else None
                    ),
                    requires_ai_review=not confirmed,
                )
            )


def _function_like_target(
    ctx: RuleContext, rel: Relationship
) -> tuple[CodeEntity, tuple[str, ...], bool] | None:
    if rel.target_entity_id is None:
        return None
    entity = ctx.by_id.get(rel.target_entity_id)
    if entity is None:
        return None
    if entity.kind in ("function", "method"):
        return entity, tuple(p.name for p in entity.parameters), True
    if entity.kind == "class":
        for e in ctx.entities:
            if e.container_id == entity.id and e.name == "__init__":
                return e, tuple(p.name for p in e.parameters), True
    return None


def _rule_r2(ctx: RuleContext) -> None:
    for claim in ctx.claims:
        if claim.claim_type == ClaimType.API_SIGNATURE:
            documented = tuple(p for p in claim.parameters if p not in ("self", "cls"))
        elif claim.claim_type == ClaimType.PARAMETER_MENTION and claim.subject:
            documented = (claim.subject,)
        else:
            continue
        rels = ctx.rels.get(claim.claim_id, [])
        if not rels or not documented:
            continue
        cprov = _claim_prov(claim, ctx.doc_sha)
        doc_ev = Evidence(
            kind="doc_claim", side=ctx.side, description=claim.original_text[:200], provenance=cprov
        )
        top = rels[0]
        if top.ambiguous:
            ctx.add(
                ConsistencyRecord(
                    key=ctx.key("R2", claim, _SENTINEL_AMBIGUOUS, "parameter:*"),
                    rule_id="R2",
                    category=Category.REMOVED_PARAMETER,
                    state=ConsistencyState.NOT_EVALUABLE,
                    evidence_status=EvidenceStatus.AMBIGUOUS_RELATIONSHIP,
                    claim=claim,
                    property="parameter:*",
                    doc_value=list(documented),
                    summary="Cannot tell which function the documented parameters belong to",
                    reasons=("ambiguous_relationship",),
                    mapping_reasons=top.reasons,
                    evidence=(doc_ev,),
                    requires_ai_review=True,
                )
            )
            continue
        if top.strength != Strength.STRONG:
            continue
        if claim.claim_type == ClaimType.PARAMETER_MENTION and not any(
            s.kind == SignalKind.HEADING_SYMBOL and s.tier == Strength.STRONG for s in top.signals
        ):
            continue
        target = _function_like_target(ctx, top)
        if target is None:
            continue
        func, names, _ = target
        if claim.claim_type == ClaimType.API_SIGNATURE and claim.subject not in (
            func.name,
            ctx.by_id[top.target_entity_id or ""].name,
        ):
            continue
        variadic = any(p.kind in ("var_positional", "var_keyword") for p in func.parameters)
        overloaded = any("overload" in d for d in func.decorators)
        redefined = sum(1 for e in ctx.entities if e.symbol_key == func.symbol_key) > 1
        identity = ctx.entity_key(func)
        code_ev = Evidence(
            kind="code_fact",
            side=ctx.side,
            description=f"{func.qualname}({', '.join(names)})",
            provenance=func.provenance,
        )
        for name in documented:
            prop = f"parameter:{name}"
            common = {
                "key": ctx.key("R2", claim, identity, prop),
                "rule_id": "R2",
                "category": Category.REMOVED_PARAMETER,
                "claim": claim,
                "entity_id": func.id,
                "entity_name": func.name,
                "property": prop,
                "doc_value": name,
                "mapping_reasons": top.reasons,
                "evidence": (doc_ev, code_ev, *_mapping_evidence(ctx.side, top)),
                "code_provenance": func.provenance,
                "exposure": func.exposure,
            }
            if name in names:
                ctx.add(
                    ConsistencyRecord(
                        **common,
                        state=ConsistencyState.CONSISTENT,
                        evidence_status=EvidenceStatus.CONFIRMED,
                        code_value="present",
                        summary=f"Parameter '{name}' exists on {func.name}",
                    )
                )
                continue
            reasons = []
            if variadic:
                reasons.append("variadic_parameters")
            if overloaded:
                reasons.append("overloaded")
            if redefined:
                reasons.append("redefined")
            potential = bool(reasons)
            ctx.add(
                ConsistencyRecord(
                    **common,
                    state=ConsistencyState.INCONSISTENT,
                    evidence_status=(
                        EvidenceStatus.POTENTIAL if potential else EvidenceStatus.CONFIRMED
                    ),
                    code_value="absent",
                    summary=f"Documented parameter '{name}' is not a parameter of {func.name}",
                    reasons=tuple(reasons),
                    requires_ai_review=potential,
                )
            )


def _is_config_name(name: str) -> bool:
    return name.upper() == name and any(ch.isalpha() for ch in name)


def _first_entity(index: SymbolIndex | None, name: str) -> CodeEntity | None:
    if index is None:
        return None
    ids = sorted(index.by_name.get(name, []))
    return index.by_id[ids[0]] if ids else None


def _rule_r3_r4(ctx: RuleContext) -> None:
    for claim in ctx.claims:
        if (
            claim.claim_type
            not in (
                ClaimType.CONFIGURATION_REFERENCE,
                ClaimType.IDENTIFIER_REFERENCE,
                ClaimType.API_SIGNATURE,
            )
            or not claim.subject
        ):
            continue
        name = claim.subject.split(".")[-1]
        r3 = claim.claim_type == ClaimType.CONFIGURATION_REFERENCE and _is_config_name(name)
        rule = "R3" if r3 else "R4"
        if claim.claim_type == ClaimType.CONFIGURATION_REFERENCE and not r3:
            continue
        category = (
            Category.RENAMED_OR_REMOVED_CONFIG_KEY if r3 else Category.RENAMED_OR_REMOVED_SYMBOL
        )
        exists_here = ctx.symbol_index.exists_in(name)
        if ctx.side == Side.BASE:
            existed = exists_here
            base_entity = _first_entity(ctx.symbol_index, name)
        else:
            existed = ctx.base_index.exists_in(name) if ctx.base_index else False
            base_entity = _first_entity(ctx.base_index, name)
        if not existed:
            continue  # never defined in base: may be external; ignore
        cprov = _claim_prov(claim, ctx.doc_sha)
        doc_ev = Evidence(
            kind="doc_claim", side=ctx.side, description=claim.original_text[:200], provenance=cprov
        )
        common = {
            "key": ctx.key(rule, claim, f"name:{name}", "exists"),
            "rule_id": rule,
            "category": category,
            "claim": claim,
            "entity_name": name,
            "property": "exists",
            "doc_value": name,
            "code_provenance": base_entity.provenance if base_entity else None,
            "exposure": base_entity.exposure if base_entity else Exposure.UNKNOWN,
        }
        if exists_here:
            ent = _first_entity(ctx.symbol_index, name)
            ev: tuple[Evidence, ...] = (doc_ev,)
            if ent is not None:
                ev = (
                    doc_ev,
                    Evidence(
                        kind="code_fact",
                        side=ctx.side,
                        description=f"{ent.kind} {ent.qualname} defined",
                        provenance=ent.provenance,
                    ),
                )
            ctx.add(
                ConsistencyRecord(
                    **common,
                    state=ConsistencyState.CONSISTENT,
                    evidence_status=EvidenceStatus.CONFIRMED,
                    code_value="present",
                    summary=f"'{name}' is defined",
                    evidence=ev,
                )
            )
            continue
        # missing at head
        if not ctx.snapshot_complete:
            ctx.add(
                ConsistencyRecord(
                    **common,
                    state=ConsistencyState.NOT_EVALUABLE,
                    evidence_status=EvidenceStatus.INSUFFICIENT_EVIDENCE,
                    code_value="unknown",
                    summary=f"'{name}' not found but the source scan is incomplete",
                    reasons=("insufficient_evidence", "source_scan_incomplete"),
                    evidence=(doc_ev,),
                    requires_ai_review=True,
                )
            )
            continue
        has_getattr = any(s.has_module_getattr for s in ctx.symbol_index.sources_by_path.values())
        string_key = any(
            sk.value == name
            for s in ctx.symbol_index.sources_by_path.values()
            for sk in s.string_keys
        )
        reasons = []
        if has_getattr:
            reasons.append("module_getattr")
        if string_key:
            reasons.append("string_key_reference")
        potential = bool(reasons)
        new_name = ctx.rename_candidates.get(name)
        evidence: list[Evidence] = [doc_ev]
        if base_entity is not None:
            evidence.append(
                Evidence(
                    kind="code_fact",
                    side=Side.BASE,
                    description=f"{base_entity.kind} {base_entity.qualname} existed in base",
                    provenance=base_entity.provenance,
                )
            )
        ctx.add(
            ConsistencyRecord(
                **common,
                state=ConsistencyState.INCONSISTENT,
                evidence_status=EvidenceStatus.POTENTIAL if potential else EvidenceStatus.CONFIRMED,
                code_value="absent",
                summary=f"Documentation references '{name}' which no longer exists",
                reasons=tuple(reasons),
                evidence=tuple(evidence),
                suggested_correction=f"Replace '{name}' with '{new_name}'" if new_name else None,
                requires_ai_review=potential,
            )
        )


def evaluate_side(
    side: Side,
    claims: Sequence[DocClaim],
    entities: Sequence[CodeEntity],
    facts: Sequence[CodeFact],
    relationships: Sequence[Relationship],
    symbol_index: SymbolIndex,
    snapshot_complete: bool,
    *,
    doc_sha: str = "0" * 40,
    base_index: SymbolIndex | None = None,
    rename_candidates: Mapping[str, str] | None = None,
    entity_key: Callable[[CodeEntity], str] | None = None,
    doc_path: Callable[[str], str] | None = None,
) -> dict[str, ConsistencyRecord]:
    ctx = RuleContext(
        side,
        claims,
        entities,
        facts,
        relationships,
        symbol_index,
        snapshot_complete,
        doc_sha=doc_sha,
        base_index=base_index if side == Side.HEAD else symbol_index,
        rename_candidates=rename_candidates or {},
        entity_key=entity_key or (lambda e: e.symbol_key),
        doc_path=doc_path or (lambda p: p),
    )
    _rule_r1(ctx)
    _rule_r2(ctx)
    _rule_r3_r4(ctx)
    return ctx.out
