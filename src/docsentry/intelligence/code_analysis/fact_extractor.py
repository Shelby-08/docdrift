import hashlib
from collections.abc import Sequence
from typing import Any

from docsentry.intelligence.code_analysis.value_extractor import extract_unit_hint
from docsentry.intelligence.models.code import CodeEntity, CodeFact, FactType


def _make_fact_id(entity_id: str, fact_type: FactType, prop: str | None, line: int) -> str:
    raw = f"{entity_id}:{fact_type.value}:{prop or ''}:{line}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _is_config_like_class(entity: CodeEntity) -> bool:
    if entity.kind != "class":
        return False
    if entity.name.endswith(("Settings", "Config", "Options", "Params")):
        return True
    for dec in entity.decorators:
        if dec == "dataclass" or dec.endswith(".dataclass"):
            return True
    for base in entity.bases:
        if base.endswith(("Settings", "Config", "BaseModel")):
            return True
    return False


def facts_from_entities(entities: Sequence[CodeEntity]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    config_classes: set[str] = {e.id for e in entities if _is_config_like_class(e)}

    for ent in entities:
        p = ent.provenance
        if ent.kind in ("function", "method"):
            sig_id = _make_fact_id(ent.id, FactType.FUNCTION_SIGNATURE, None, p.line)
            param_list = [param.model_dump() for param in ent.parameters]
            facts.append(
                CodeFact(
                    fact_id=sig_id,
                    fact_type=FactType.FUNCTION_SIGNATURE,
                    entity_id=ent.id,
                    entity_name=ent.name,
                    value=ent.name,
                    resolved=True,
                    unit_hint=extract_unit_hint(ent.name),
                    provenance=p,
                    details={"parameters": param_list, "is_async": ent.is_async},
                )
            )

            for param in ent.parameters:
                if param.default is not None:
                    def_id = _make_fact_id(ent.id, FactType.PARAMETER_DEFAULT, param.name, p.line)
                    unit = extract_unit_hint(param.name) or extract_unit_hint(ent.name)
                    facts.append(
                        CodeFact(
                            fact_id=def_id,
                            fact_type=FactType.PARAMETER_DEFAULT,
                            entity_id=ent.id,
                            entity_name=ent.name,
                            property=param.name,
                            value=param.default.value if param.default.resolved else None,
                            resolved=param.default.resolved,
                            unit_hint=unit,
                            provenance=p,
                            details={"default": param.default.model_dump()},
                        )
                    )
                if param.annotation is not None:
                    ann_id = _make_fact_id(ent.id, FactType.PARAMETER_TYPE, param.name, p.line)
                    facts.append(
                        CodeFact(
                            fact_id=ann_id,
                            fact_type=FactType.PARAMETER_TYPE,
                            entity_id=ent.id,
                            entity_name=ent.name,
                            property=param.name,
                            value=param.annotation,
                            resolved=True,
                            provenance=p,
                            details={"annotation": param.annotation},
                        )
                    )

            if ent.return_annotation is not None:
                ret_id = _make_fact_id(ent.id, FactType.RETURN_TYPE, None, p.line)
                facts.append(
                    CodeFact(
                        fact_id=ret_id,
                        fact_type=FactType.RETURN_TYPE,
                        entity_id=ent.id,
                        entity_name=ent.name,
                        value=ent.return_annotation,
                        resolved=True,
                        provenance=p,
                        details={"annotation": ent.return_annotation},
                    )
                )

        elif ent.kind == "class":
            cls_id = _make_fact_id(ent.id, FactType.CLASS_STRUCTURE, None, p.line)
            facts.append(
                CodeFact(
                    fact_id=cls_id,
                    fact_type=FactType.CLASS_STRUCTURE,
                    entity_id=ent.id,
                    entity_name=ent.name,
                    value=list(ent.bases),
                    resolved=True,
                    provenance=p,
                    details={"bases": list(ent.bases), "decorators": list(ent.decorators)},
                )
            )

        elif ent.kind == "constant":
            c_id = _make_fact_id(ent.id, FactType.CONSTANT_VALUE, None, p.line)
            val = ent.value.value if (ent.value and ent.value.resolved) else None
            resolved = ent.value.resolved if ent.value else False
            details: dict[str, Any] = {"source_expr": ent.value.source_expr if ent.value else ""}
            if ent.alias_target:
                details["alias_target"] = ent.alias_target
            facts.append(
                CodeFact(
                    fact_id=c_id,
                    fact_type=FactType.CONSTANT_VALUE,
                    entity_id=ent.id,
                    entity_name=ent.name,
                    value=val,
                    resolved=resolved,
                    unit_hint=extract_unit_hint(ent.name),
                    provenance=p,
                    details=details,
                )
            )

        elif ent.kind == "config_key":
            cfg_id = _make_fact_id(ent.id, FactType.CONFIG_DEFAULT, None, p.line)
            val = ent.value.value if (ent.value and ent.value.resolved) else None
            resolved = ent.value.resolved if ent.value else False
            details = {"source_expr": ent.value.source_expr if ent.value else ""}
            if isinstance(val, str) and val.isdigit():
                details["numeric"] = int(val)
            facts.append(
                CodeFact(
                    fact_id=cfg_id,
                    fact_type=FactType.CONFIG_DEFAULT,
                    entity_id=ent.id,
                    entity_name=ent.name,
                    value=val,
                    resolved=resolved,
                    unit_hint=extract_unit_hint(ent.name),
                    provenance=p,
                    details=details,
                )
            )

        elif ent.kind == "class_variable":
            if ent.container_id in config_classes:
                cfg_id = _make_fact_id(ent.id, FactType.CONFIG_DEFAULT, ent.name, p.line)
                val = ent.value.value if (ent.value and ent.value.resolved) else None
                resolved = ent.value.resolved if ent.value else False
                details = {"source_expr": ent.value.source_expr if ent.value else ""}
                if isinstance(val, str) and val.isdigit():
                    details["numeric"] = int(val)
                facts.append(
                    CodeFact(
                        fact_id=cfg_id,
                        fact_type=FactType.CONFIG_DEFAULT,
                        entity_id=ent.id,
                        entity_name=ent.name,
                        property=ent.name,
                        value=val,
                        resolved=resolved,
                        unit_hint=extract_unit_hint(ent.name),
                        provenance=p,
                        details=details,
                    )
                )

    return facts
